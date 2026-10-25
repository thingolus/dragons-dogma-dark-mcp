"""LOT v16 encounter layout reader. Independent implementation; MIT, Thingolus.

Field order researched against Chris Purnell's dd-tools lot2xml. IDs, scripts,
unknown flags and relationships stay read-only; scalar edits never resize records.
"""

from .game_parameters import Field, Reader, invalid

COMMON = "i:mAreaHitNo b:mIsSetHp f:mHpRatio b:mIsSetAtkPow f:mAtkPowRatio b:mIsSetDefence f:mDefenceRatio b:mIsSetMagicPow f:mMagicPowRatio b:mIsSetMagicDef f:mMagicDefRatio i:mAIKnowledgeFlag i:mAIKind b:mIsAINoTarget b:mIsUseItemEveryone b:mIsDragonBallDrop i:mSetID s:mName i:mOrder v:mPosition v:mAngle v:mScale f:mDrawDistance b:mIsOnSplitAreaIgnore"
ENEMY = (
    "i:mLifePointGroup b:mUseFirstSetThinkTbl i:mStartTableNo b:mBossFlag b:mBgmBossFlag i:mEmItemFlag i:mEmItemTable i:mDieSet b:mCorpseQuickDiscreate b:mIsDieEraseTimeExtend b:mRandomSetIgnore i:mExperienceOW s:mFsmPath b:sensorRadiusEnabled f:sensorRadiusRatio "
    + COMMON
)
PLACEABLE = (
    "h:mSetTableID h:mSetTableIDNight h:mSetItemNo h:mSetItemNoNight i:mStartHour i:mEndHour i:mFree00 i:mFree01 i:mAngleType i:mFlag "
    + COMMON
)
PREFIXES = {
    4: "i:mEquipType b:mIsLeader b:mIsWeaponHandStart b:mIsBallistaLicense",
    5: "i:mEquipType b:mIsLeader b:mIsWeaponHandStart",
    7: "i:mWolfType b:mIsRandamScale f:mWolfScale",
    10: "b:mIsWallStart b:mIsOptCamStart",
    14: "i:mPartsVariationNo",
    17: "i:mEquipType i:mPartsVariationNo",
    19: "b:mHoverMainMode b:mbOmBreakCheck i:mOmBreakGroup i:mOmBreakID b:mHoverActionStart",
    20: "i:mPowerUpLv",
    23: "i:mType i:mWeaponType i:mTuskType b:mIsWest b:mIsKakusya i:mKakusyaExp f:mKakusyaRestHpRate f:mKakusyaLegDP f:mKakusyaLegBP",
    24: "i:mInitMediumBreak",
    25: "i:mGolemNo",
    26: "i:mGolemNo i:mMediumRegionNo",
    27: "b:mIsReqDieCamera",
    28: "f:mStartWaitTime",
    30: "i:mTentacleMagicCanNum i:mTentacleWarpMaxNum v:mTentacleWarpExtent",
    32: "i:mSeqButtleSts",
    33: "b:mIsDieSet",
    34: "i:mSetType b:mNonFlySet b:mOriginalTalk b:lichPossession b:disableCirclingFlight",
    35: "b:deathSpecialPlacement f:deathSpecialPlacementFrame",
    45: "f:mLifeTime b:mIsSoundOff",
    66: "i:mType b:mIsWeaponInitRemove v:mWeaponInitPos v:mWeaponInitAngle",
    69: "i:mEquipType b:mIsLeader b:mIsWeaponHandStart b:mIsBallistaLicense i:mType",
}
for original, aliases in (
    (5, [6]),
    (7, [8, 9, 56, 57]),
    (10, [11, 12, 13, 58, 59, 60, 61, 62]),
    (14, [15, 16, 18, 22, 63, 64, 65]),
    (30, [70]),
    (33, [67]),
):
    for alias in aliases:
        PREFIXES[alias] = PREFIXES[original]
for kind in (3, 21, 29, 31, 36, 37, 38, 39, 40, 41, 42, 43, 44, 68, 71, 73):
    PREFIXES[kind] = ""
SCHEMAS = {kind: prefix + " " + ENEMY for kind, prefix in PREFIXES.items()}
SCHEMAS.update(
    {
        46: "i:mLightGroup b:mOverwriteLightGroup i:mTransMode b:mOverwriteTransMode " + COMMON,
        48: PLACEABLE,
        49: "s:mFSMPath " + PLACEABLE,
        50: "h:mSeGroupId h:mSePriority h:mMapIconType s:mFSMPath " + PLACEABLE,
        51: "f:mCheckAngle f:mCheckRange " + PLACEABLE,
        52: "h:mSeGroupId h:mSePriority h:mMapIconType " + PLACEABLE,
        53: "h:mLockMsgNo h:mOutMsgNo h:mOpenMsgNo f:mCheckAngle f:mCheckRange h:mSeGroupId h:mSePriority h:mMapIconType "
        + PLACEABLE,
    }
)
NPC = "i:mNpcPriority s:mFSMPath i:mNpcId b:mScrAdjustOff b:mObjAdjustOff i:mPriority b:mGoodsOff i:mSimpleModelType i:mPartsVariationNo i:mClothType b:mUseMouseJoint i:mHumanEnemyKind i:mHumanEnemyID i:mRank i:mMultiNpcKind b:mUse24Schedule b:mIsHumanEnemyLeader i:mExperienceOW"
WAIT = "b:mWaitParamExist i:Type i:Flag i:WaitActNo f:BaseWaitTimer f:RandWaitTimer i:BehaviorActNo f:BaseBehaviourTimer f:RandBehaviourTimer"
TARGETS = {
    "cAISensorTargetStageAction": "i:mStageActionType i:mPawnID i:mOnOffKind f:mResetTime i:mWeight b:CHK_TYPE h:ITEM_NO b:ITEM_NUM a:mActParamIdx a:mActParamQuestNo",
    "cAISensorTargetGeneralPoint": "i:mGroup i:mId i:mActType b:mIsAllDay i:mSTime i:mETime i:mShape v:mSize",
    "cAISensorTargetNpc": "b:mEnable i:mActType i:mMotType f:mActFrame b:mNearFlag b:mRotFlag b:mIsAllDay i:mStartTime i:mEndTime b:mFix i:mMessQuestNo i:mMessId f:mMessDispSec i:mNpcId",
}
TARGET_COMMON = (
    "i:mTypeBit i:mSndLv i:mStatusFlag v:mPos v:mDir f:mRange i:mObjectID i:mAttr f:mSphereRange i:mJntNo"
)
EDITABLE = {
    "mHpRatio",
    "mAtkPowRatio",
    "mDefenceRatio",
    "mMagicPowRatio",
    "mMagicDefRatio",
    "mIsSetHp",
    "mIsSetAtkPow",
    "mIsSetDefence",
    "mIsSetMagicPow",
    "mIsSetMagicDef",
    "mPosition",
    "mAngle",
    "mScale",
    "mDrawDistance",
    "mExperienceOW",
    "sensorRadiusEnabled",
    "sensorRadiusRatio",
    "mWolfScale",
    "mStartWaitTime",
    "mLifeTime",
}


def encounter_fields(raw):
    r = Reader(raw)
    if raw[:8] != b"lot\0\x10\0\0\0":
        invalid("Only reviewed LOT version 16 is supported.")
    r.pos = 8
    count = r.number("I")
    if count > 10000:
        invalid("Encounter record budget exceeded.")

    def fields(schema, path):
        for token in schema.split():
            kind, name = token.split(":")
            key = f"{path}/{name}"
            editable = name in EDITABLE
            if kind == "s":
                at = r.pos
                value = r.string(len(raw))
                r.fields.append(Field(key, name, "string", at, r.pos - at, value))
            elif kind == "v":
                for component in range(3):
                    r.scalar(f"{key}/{component}", name, "f32", "f", len(raw), editable)
            elif kind == "a":
                n = r.number("I")
                if n > 4096:
                    invalid("Encounter target array exceeds bounds.")
                for i in range(n):
                    r.scalar(f"{key}/{i}", name, "s16", "h", len(raw), False)
            else:
                # Some engine byte flags are bitmasks, so do not assume all are bool.
                storage, typename = {
                    "i": ("i", "s32"),
                    "h": ("h", "s16"),
                    "b": ("B", "u8"),
                    "f": ("f", "f32"),
                }[kind]
                minimum = -1 if name == "mExperienceOW" else 0 if editable else None
                maximum = 1 if kind == "b" and editable else None
                r.scalar(key, name, typename, storage, len(raw), editable, minimum, maximum)

    def target(path):
        fields("i:mpTarget", path)
        if not r.fields[-1].value:
            return
        fields("s:class", path)
        name = r.fields[-1].value
        if name not in TARGETS:
            invalid("Unreviewed encounter target class.")
        fields(TARGETS[name] + " " + TARGET_COMMON, path)

    for i in range(count):
        path = f"$/{i}"
        fields("i:index i:type", path)
        kind = r.fields[-1].value
        if kind == 47:
            fields(NPC, path)
            target(path + "/target")
            fields(WAIT, path + "/wait")
            fields(COMMON, path)
        elif kind == 54:
            target(path + "/target")
        elif kind in SCHEMAS:
            fields(SCHEMAS[kind], path)
        else:
            invalid(f"Unreviewed encounter type {kind}.")
    if r.pos != len(raw):
        invalid("Encounter schema did not consume the complete resource.")
    return {"format": "lot_0010", "records": count}, r.fields
