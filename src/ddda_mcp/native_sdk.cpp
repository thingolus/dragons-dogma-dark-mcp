// Callback-only native event provider. Copyright (c) 2026 Thingolus. MIT.
#include "native_sdk.hpp"
#include "sdk_build_identity.hpp"
#include <windows.h>
#include <bcrypt.h>
#include <MinHook.h>
#include <cmath>
#include <cstring>
#include <cstddef>
static_assert(sizeof(void*)==4, "DDDA native SDK requires Win32");
namespace {
SRWLOCK gate=SRWLOCK_INIT;
SRWLOCK lifecycle=SRWLOCK_INIT;
struct LifecycleLock {
    bool acquired;
    LifecycleLock():acquired(TryAcquireSRWLockExclusive(&lifecycle)!=0){}
    ~LifecycleLock(){if(acquired)ReleaseSRWLockExclusive(&lifecycle);}
};
volatile LONG running=0, active=0, errors=0, dropped=0, contended=0;
ddda::NativeEvent ring[512];
unsigned head=0, count=0, sequence=0, samples=0, lifetime=0;
void* original=nullptr;
bool created=false;
struct Item {short id; unsigned short quantity;};
struct Previous {
    unsigned char* actor=nullptr; unsigned stage=0, incarnation=0;
    ULONGLONG tick=0; ddda::NativeEvent event{};
    Item items[256]{}; unsigned count=0; bool inventory=false;
} previous[2];
bool readable(const void* pointer, size_t bytes) {
    if(!pointer || !bytes) return false;
    MEMORY_BASIC_INFORMATION m{};
    if(!VirtualQuery(pointer,&m,sizeof(m)) || m.State!=MEM_COMMIT || (m.Protect&(PAGE_GUARD|PAGE_NOACCESS)))return false;
    const auto start=reinterpret_cast<std::uintptr_t>(pointer);
    const auto end=reinterpret_cast<std::uintptr_t>(m.BaseAddress)+m.RegionSize;
    return start<=end && bytes<=end-start;
}
template<class T> T get(const unsigned char* p,size_t offset=0) { T value; std::memcpy(&value,p+offset,sizeof(T)); return value; }
bool verifyExecutable() {
    wchar_t path[32768]; const DWORD length=GetModuleFileNameW(nullptr,path,32768);
    if(!length || length>=32768)return false;
    HANDLE file=CreateFileW(path,GENERIC_READ,FILE_SHARE_READ,nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(file==INVALID_HANDLE_VALUE)return false;
    BCRYPT_ALG_HANDLE algorithm=nullptr; BCRYPT_HASH_HANDLE hash=nullptr;
    unsigned char digest[32]{}; unsigned char buffer[65536]; DWORD bytes=0; unsigned total=0;
    bool ok=BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)>=0;
    if(ok)ok=BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)>=0;
    while(ok) {
        if(!ReadFile(file,buffer,sizeof(buffer),&bytes,nullptr)){ok=false;break;}
        if(!bytes)break;
        total+=bytes;if(total>128*1024*1024){ok=false;break;}
        ok=BCryptHashData(hash,buffer,bytes,0)>=0;
    }
    if(ok)ok=BCryptFinishHash(hash,digest,sizeof(digest),0)>=0;
    if(hash)BCryptDestroyHash(hash);if(algorithm)BCryptCloseAlgorithmProvider(algorithm,0);CloseHandle(file);
    return ok && !std::memcmp(digest,ddda_game_sha256,sizeof(digest));
}
void emit(ddda::NativeEvent event,ddda::EventKind kind) {
    event.kind=static_cast<unsigned>(kind);event.sequence=++sequence;
    if(count==512){InterlockedIncrement(&dropped);return;}
    ring[(head+count)%512]=event;++count;
}
unsigned quantity(const Item* items,unsigned n,short id){unsigned result=0;for(unsigned i=0;i<n;i++)if(items[i].id==id)result+=items[i].quantity;return result;}
bool inventory(unsigned role, Item* out, unsigned& n) {
    auto manager=*reinterpret_cast<unsigned char**>(0x18fa4d4);const auto offset=role*0x11e8+0x178;
    if(!readable(manager,offset+0x18))return false;
    auto container=manager+offset;n=get<unsigned>(container,8);auto table=get<unsigned char**>(container,0x14);
    if(n>256 || (n&&!readable(table,n*4)))return false;
    for(unsigned i=0;i<n;i++){
        auto entry=table[i];if(!readable(entry,0x24))return false;
        out[i]={get<short>(entry,0x10),get<unsigned short>(entry,0x12)};
        if(table[i]!=entry)return false;
    }
    return *reinterpret_cast<unsigned char**>(0x18fa4d4)==manager && n==get<unsigned>(container,8) && table==get<unsigned char**>(container,0x14);
}
void observe(unsigned char* actor,float request) {
    if(!std::isfinite(request) || !readable(actor,0x585c) || get<unsigned char*>(actor,0x32bc)!=actor)return;
    auto gs=*reinterpret_cast<unsigned char**>(0x18fa4bc);
    if(!readable(gs,0xa7ec0+0x2ac)||get<unsigned>(gs)!=0x155db00)return;
    auto info=get<unsigned char*>(actor,0x3dec);int role=info==gs+0xa76d0?0:info==gs+0xa7ec0?1:-1;
    if(role<0 || get<unsigned>(actor)!=(role?0x15e8468u:0x15e90d0u))return;
    const unsigned flags=get<unsigned char>(actor,0x206d);
    if(role?(!(flags&4)||get<unsigned>(actor,0x5854)!=0):!(flags&2))return;
    unsigned stage=get<unsigned>(gs,0x34);if(!stage)return;
    auto& prev=previous[role];const auto now=GetTickCount64();
    bool replaced=prev.actor!=actor||prev.stage!=stage;
    if(!replaced && now-prev.tick<200)return;
    if(replaced){prev={};prev.actor=actor;prev.stage=stage;prev.incarnation=++lifetime;}
    ddda::NativeEvent event{};event.role=role;event.stage=stage;event.incarnation=prev.incarnation;
    event.requested_delta=request;event.action=get<unsigned>(actor,0x2dd4);event.vocation=get<unsigned char>(info,0x10);
    for(unsigned i=0;i<3;i++){event.position[i]=get<float>(actor,0xe0+4*i);if(!std::isfinite(event.position[i]))return;}
    event.available=1;
    auto n=get<unsigned>(actor,0x1d0c);auto list=get<unsigned char**>(actor,0x1d18);
    if(n&&n<=64&&readable(list,n*4)){
        auto life=list[0];
        if(readable(life,0x1b8)&&get<unsigned char*>(life,0x1b4)==actor){
            event.hp=get<float>(life,8);event.hp_max=get<float>(life,12);event.stamina=get<float>(info,0x2a8);
            if(std::isfinite(event.hp)&&std::isfinite(event.hp_max)&&std::isfinite(event.stamina)&&event.hp>=0&&event.hp_max>=0&&event.stamina>=0&&list[0]==life&&get<unsigned char*>(life,0x1b4)==actor)event.available|=2;
        }
    }
    if(!(event.available&2))event.hp=event.hp_max=event.stamina=0;
    Item items[256]{};unsigned itemCount=0;bool inv=inventory(role,items,itemCount);
    if(inv)event.available|=4;
    if(*reinterpret_cast<unsigned char**>(0x18fa4bc)!=gs||get<unsigned>(gs,0x34)!=stage||get<unsigned char*>(actor,0x3dec)!=info)return;
    if(replaced)emit(event,ddda::EventKind::actor_replaced);
    emit(event,ddda::EventKind::sample);emit(event,ddda::EventKind::stamina_request);
    if(prev.tick&&(event.available&2)&&(prev.event.available&2)&&event.hp!=prev.event.hp){auto delta=event;delta.before=prev.event.hp;delta.after=event.hp;emit(delta,ddda::EventKind::hp_changed);}
    if(prev.tick&&inv&&prev.inventory){
        // Visit each ID once, including items removed entirely from the inventory.
        short visited[512];unsigned visitedCount=0;
        for(unsigned i=0;i<itemCount+prev.count;i++){
            short id=i<itemCount?items[i].id:prev.items[i-itemCount].id;bool seen=false;
            for(unsigned j=0;j<visitedCount;j++)if(visited[j]==id)seen=true;if(seen)continue;visited[visitedCount++]=id;
            unsigned before=quantity(prev.items,prev.count,id),after=quantity(items,itemCount,id);
            if(before!=after){auto delta=event;delta.item_id=id;delta.quantity=after;delta.before=static_cast<float>(before);delta.after=static_cast<float>(after);emit(delta,ddda::EventKind::inventory_delta);}
        }
    }
    prev.tick=now;prev.event=event;prev.inventory=inv;prev.count=itemCount;
    if(inv)std::memcpy(prev.items,items,itemCount*sizeof(Item));++samples;
}
void __cdecl onActor(unsigned char* actor,float request) {
    InterlockedIncrement(&active);
    if(InterlockedCompareExchange(&running,0,0)){
        if(TryAcquireSRWLockExclusive(&gate)){
            __try {if(ResearchHealthy()==1&&!ResearchErrors())observe(actor,request);else InterlockedIncrement(&errors);}
            __except(EXCEPTION_EXECUTE_HANDLER){InterlockedIncrement(&errors);}
            ReleaseSRWLockExclusive(&gate);
        }else InterlockedIncrement(&contended);
    }
    InterlockedDecrement(&active);
}
// The reviewed function takes actor in EAX and requested delta at ESP+4.
// Preserve integer flags/registers and the complete x87/SSE state around C++.
__declspec(naked) void staminaHook(){__asm {
    pushfd
    pushad
    mov ebp,esp
    sub esp,528
    and esp,0xfffffff0
    fxsave [esp]
    push dword ptr [ebp+40]
    push eax
    call onActor
    add esp,8
    fxrstor [esp]
    mov esp,ebp
    popad
    popfd
    jmp dword ptr [original]
}}
}
DDDA_EXPORT int DDDA_CALL DdSdkStart(){
    LifecycleLock lock;if(!lock.acquired)return 0;
    if(InterlockedCompareExchange(&running,0,0)||InterlockedCompareExchange(&active,0,0)||reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr))!=0x400000||!verifyExecutable()||ResearchHealthy()!=1||ResearchErrors())return 0;
    auto address=reinterpret_cast<void*>(0x400000+ddda_stamina_rva);
    if(!readable(address,sizeof(ddda_stamina_bytes))||std::memcmp(address,ddda_stamina_bytes,sizeof(ddda_stamina_bytes)))return 0;
    AcquireSRWLockExclusive(&gate);head=count=sequence=samples=0;errors=dropped=contended=0;previous[0]={};previous[1]={};ReleaseSRWLockExclusive(&gate);
    if(!created){
        if(MH_CreateHook(address,reinterpret_cast<void*>(staminaHook),&original)!=MH_OK)return 0;
        created=true;
    }
    InterlockedExchange(&running,1);
    if(MH_EnableHook(address)!=MH_OK){InterlockedExchange(&running,0);return 0;}
    return 1;
}
DDDA_EXPORT int DDDA_CALL DdSdkStop(){
    LifecycleLock lock;if(!lock.acquired)return 0;
    InterlockedExchange(&running,0);if(!created)return 1;
    auto address=reinterpret_cast<void*>(0x400000+ddda_stamina_rva);
    const auto disabled=MH_DisableHook(address);
    if(disabled!=MH_OK&&disabled!=MH_ERROR_DISABLED)return 0;
    auto deadline=GetTickCount64()+250;while(InterlockedCompareExchange(&active,0,0)&&GetTickCount64()<deadline)Sleep(1);
    if(InterlockedCompareExchange(&active,0,0)||std::memcmp(address,ddda_stamina_bytes,sizeof(ddda_stamina_bytes)))return 0;
    // A callback can have left onActor while still returning through the naked
    // stub/trampoline. Keep that executable allocation until process exit.
    // Start reuses it only after checking the restored original signature.
    return 1;
}
DDDA_EXPORT unsigned DDDA_CALL DdSdkReadEvents(ddda::NativeEvent* output,unsigned capacity){
    if(!output||!capacity||capacity>512)return 0;
    AcquireSRWLockExclusive(&gate);unsigned n=count<capacity?count:capacity;
    for(unsigned i=0;i<n;i++)output[i]=ring[(head+i)%512];head=(head+n)%512;count-=n;ReleaseSRWLockExclusive(&gate);return n;
}
DDDA_EXPORT int DDDA_CALL DdSdkStatus(ddda::NativeStatus* out){
    if(!out||out->size!=sizeof(*out)||out->version!=1)return 0;
    AcquireSRWLockExclusive(&gate);*out={sizeof(*out),1,static_cast<unsigned>(running),count,static_cast<unsigned>(dropped),static_cast<unsigned>(errors),samples,static_cast<unsigned>(active),static_cast<unsigned>(contended)};ReleaseSRWLockExclusive(&gate);return 1;
}
