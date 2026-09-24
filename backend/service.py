
import uuid
import random
import os
import jwt
import datetime
from dotenv import load_dotenv

from backend.cctv_validation import CCTVValidationError, CCTVValidationResult, validate_cctv
from backend.error import NoUsableCCTVError
from backend.location_name import build_cctv_display_name
from backend.repository import change_game_status, create_result, create_user_and_game, delete_unusable_pending_question, get_cctv, get_cctv_health_candidates, get_cctv_health_count, get_current_stage, get_gameID, get_gameIDS_byquetionUID, get_game_question_cctvs, get_question_create_at, get_random_cctv, get_random_cctvs, get_ranking, get_life, get_usable_cctv_candidates, quest_result, save_answer, save_cctv_health, save_question, select_question
from backend.schema import CCTV, Des, Option, Question, Rank,Raw_rank, Road_class, Send_data

load_dotenv()

MAX_CCTV_SELECTION_ATTEMPTS = 5
CCTV_POOL_FRESHNESS = datetime.timedelta(hours=12)
CCTV_HEALTH_RECHECK_AFTER = datetime.timedelta(minutes=30)
CCTV_POOL_REFRESH_BATCH_SIZE = 5
CCTV_POOL_BOOTSTRAP_TARGET_SIZE = 50
CCTV_SELECTION_CANDIDATE_SCAN_SIZE = 100
OPTION_SELECTION_CANDIDATE_COUNT = 100


def _location_keys(cctv: CCTV) -> tuple[str, str]:
    road_name = " ".join((cctv.road_name or "").strip().lower().split())
    display_name = " ".join(build_cctv_display_name(cctv).strip().lower().split())
    return road_name, display_name


def sev_rancctv(
    require_usable: bool = False,
    *,
    excluded_road_names: set[str] | None = None,
    excluded_display_names: set[str] | None = None,
):
    if not require_usable:
        return get_random_cctv()

    excluded_roads = excluded_road_names or set()
    excluded_names = excluded_display_names or set()
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    candidates = get_usable_cctv_candidates(
        now - CCTV_POOL_FRESHNESS,
        CCTV_SELECTION_CANDIDATE_SCAN_SIZE,
    )
    seen_ids = {cctv.ID for cctv in candidates}
    if len(candidates) < CCTV_SELECTION_CANDIDATE_SCAN_SIZE:
        candidates.extend(
            get_cctv_health_candidates(
                now - CCTV_HEALTH_RECHECK_AFTER,
                CCTV_SELECTION_CANDIDATE_SCAN_SIZE - len(candidates),
                seen_ids,
            )
        )

    validation_attempts = 0
    for cctv in candidates:
        road_name, display_name = _location_keys(cctv)
        if road_name and road_name in excluded_roads:
            continue
        if display_name and display_name in excluded_names:
            continue
        if validation_attempts >= MAX_CCTV_SELECTION_ATTEMPTS:
            break
        validation_attempts += 1
        try:
            validate_and_record_cctv(cctv)
            return cctv
        except CCTVValidationError:
            continue
    raise NoUsableCCTVError()


def validate_and_record_cctv(
    cctv: CCTV,
    *,
    force_refresh: bool = False,
) -> CCTVValidationResult:
    checked_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    try:
        result = validate_cctv(cctv, force_refresh=force_refresh)
    except CCTVValidationError as exc:
        save_cctv_health(cctv.ID, False, None, str(exc)[:255], checked_at)
        raise
    save_cctv_health(cctv.ID, True, result.quality_score, None, checked_at)
    return result


def refresh_cctv_pool(batch_size: int | None = None) -> dict[str, int]:
    if batch_size is None:
        checked_count = get_cctv_health_count()
        if checked_count < CCTV_POOL_BOOTSTRAP_TARGET_SIZE:
            batch_size = max(
                CCTV_POOL_REFRESH_BATCH_SIZE,
                CCTV_POOL_BOOTSTRAP_TARGET_SIZE - checked_count,
            )
        else:
            batch_size = CCTV_POOL_REFRESH_BATCH_SIZE
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    candidates = get_cctv_health_candidates(
        now - CCTV_HEALTH_RECHECK_AFTER,
        batch_size,
    )
    checked = usable = unusable = 0
    for cctv in candidates:
        checked += 1
        try:
            validate_and_record_cctv(cctv, force_refresh=True)
            usable += 1
        except CCTVValidationError:
            unusable += 1
    return {"checked": checked, "usable": usable, "unusable": unusable}


def _game_location_exclusions(game_uuid: str) -> tuple[set[str], set[str]]:
    roads: set[str] = set()
    names: set[str] = set()
    for cctv in get_game_question_cctvs(game_uuid):
        road_name, display_name = _location_keys(cctv)
        if road_name:
            roads.add(road_name)
        if display_name:
            names.add(display_name)
    return roads, names


def _build_unique_option_entries(
    answer_cctv: CCTV,
    option_count: int,
) -> list[tuple[CCTV, str]]:
    answer_road, answer_name = _location_keys(answer_cctv)
    selected = [(answer_cctv, build_cctv_display_name(answer_cctv))]
    used_ids = {answer_cctv.ID}
    used_roads = {answer_road} if answer_road else set()
    used_names = {answer_name} if answer_name else set()

    for candidate in get_random_cctvs(OPTION_SELECTION_CANDIDATE_COUNT):
        road_name, display_name = _location_keys(candidate)
        if candidate.ID in used_ids:
            continue
        if road_name and road_name in used_roads:
            continue
        if display_name and display_name in used_names:
            continue
        selected.append((candidate, build_cctv_display_name(candidate)))
        used_ids.add(candidate.ID)
        if road_name:
            used_roads.add(road_name)
        if display_name:
            used_names.add(display_name)
        if len(selected) == option_count:
            break

    if len(selected) != option_count:
        raise NoUsableCCTVError()
    random.shuffle(selected)
    return selected

def sev_cctv_byid(id:int):
    return get_cctv(id)

ran_name= [
    "塞車的人",
    "路怒症",
    "在客運上睡著的人",
    "新手駕駛",
    "老司機",
    "飛機駕駛",
    "愛睏女司機",
    "沒看過中間的後視鏡",
    "經過休息站忘記加油",
    "遠光燈沒關",
    "蠻牛套咖啡"
]
def create_game_session(name:str|None,email:str|None) -> str:
    
    if name is None or name == "":
        input_name = random.choice(ran_name)
    else:
        input_name = name

    gUUID = uuid.uuid4().hex
    create_user_and_game(input_name,email,gUUID)

    return gUUID

# 先排分數，在排耗時，列出排行，如果相同則並列。再依據比例計算排行
def ranking()-> list[Rank]:
    raw_list = get_ranking()

    ranklist = []
    for k,v in enumerate(raw_list):
        if k == 0:
            rank = 1
        elif (
            v.score == raw_list[k - 1].score
            and v.total_time == raw_list[k - 1].total_time
        ):
            rank = ranklist[-1].id
        else:
            rank = k + 1

        ranklist.append(
            Rank(
                id=rank,
                name=v.name,
                score=v.score,
                total_stage=v.total_stage,
                total_time=v.total_time,
                finish_at=v.finish_at,
                percent=f"{rank / len(raw_list):.2%}"
            )
        )
    return ranklist

ROAD_CLASS_NAME = {
    Road_class.NATIONAL: "國道",
    Road_class.PROVINCIAL_EXPRESSWAY: "快速道路",
    Road_class.CITY_EXPRESSWAY: "市區快速道路",
    Road_class.PROVINCIAL: "省道",
    Road_class.COUNTY: "縣道",
    Road_class.TOWNSHIP: "鄉道",
    Road_class.CITY: "市道",
}
def create_question(gameUUID:str,option_count:int) ->Question:
    # 先做最粗糙版本(
    # 1.隨機選擇一個CCTV 
    # 2.接著取ID生成UUID 
    # 3.在隨機挑三個點
    # 4.存成option 
    # 5.打包送出
    key = os.getenv("TOKEN_PW")
    # Validate before generating the token/options or writing the question row,
    # so a broken camera cannot leave a saved but unplayable question behind.
    excluded_roads, excluded_names = _game_location_exclusions(gameUUID)
    quest_cctv = sev_rancctv(
        require_usable=True,
        excluded_road_names=excluded_roads,
        excluded_display_names=excluded_names,
    )
    questionUUID = uuid.uuid4().hex
    payload = {
        "gameUUID":gameUUID,
        "questionUUID":questionUUID,
        "cctvID":quest_cctv.ID,
        "exp":datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
        }
    quest_cctv_token = jwt.encode(payload,key,algorithm="HS256")
    raw_options = _build_unique_option_entries(quest_cctv, option_count)
    options = []
    for j, (k, display_name) in enumerate(raw_options):
        option = Option(
            id=j,
            name=display_name,
        )
        if k.ID == quest_cctv.ID:
            ansID = j
        options.append(option)
    life = get_life(gameUUID)
    des = Des(
        dir=quest_cctv.dir,
        class_type=ROAD_CLASS_NAME[Road_class(quest_cctv.road_class)],
        name=quest_cctv.road_name,
        mile=quest_cctv.mile,
    )
    now_stage = get_current_stage(gameUUID)
    gameID = get_gameID(gameUUID)
    question = Question(
        questionID=questionUUID,
        question_cctvUUID=quest_cctv_token,
        game_stage=now_stage,
        options=options,
        life=life,
        des=des
    )
    save_question(gameID,question,ansID,quest_cctv.ID)
    return question

def search_question(gameUUID:str) ->Question|None:
    gameid = get_gameID(gameUUID)
    life = get_life(gameUUID)
    stage  =get_current_stage(gameUUID)
    

    raw = select_question(gameid,stage)
    if raw is None:
        return None
    
    quest_cctv = sev_cctv_byid(raw.question_cctvintID)

    try:
        validate_and_record_cctv(quest_cctv)
    except CCTVValidationError:
        # A pending question may have been created before validation existed,
        # or its camera may have failed since it was saved. Remove only that
        # unanswered row; the route will immediately create a validated redraw.
        if delete_unusable_pending_question(gameid, stage):
            return None
        raise

    payload = {
            "gameUUID":gameUUID,
            "questionUUID":raw.questionUUID,
            "cctvID":quest_cctv.ID,
            "exp":datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=10)
            }
    key = os.getenv("TOKEN_PW")
    quest_cctv_token = jwt.encode(payload,key,algorithm="HS256")
    des = Des(
        dir=quest_cctv.dir,
        class_type=ROAD_CLASS_NAME[Road_class(quest_cctv.road_class)],
        name=quest_cctv.road_name,
        mile=quest_cctv.mile,
    )
    question = Question(
        questionID=raw.questionUUID,
        question_cctvUUID=quest_cctv_token,
        game_stage=raw.game_stage,
        des = des,
        options=raw.options,
        life=life
    )
    print("gameid:", gameid)
    print("stage:", stage)
    print("raw:", raw)
    return question

def create_quest_stream(token:str) -> CCTVValidationResult:
    key = os.getenv("TOKEN_PW")
    data =jwt.decode(token,key,algorithms=["HS256"])
    cctvID = data["cctvID"]
    cctv = get_cctv(cctvID)

    return validate_and_record_cctv(cctv)

def send_answer(answer: Send_data):
    gameIds = get_gameIDS_byquetionUID(answer.questionID)
    start_at = get_question_create_at(answer.questionID)
    taiwan_tz = datetime.timezone(datetime.timedelta(hours=8))
    start_at = start_at.replace(tzinfo=taiwan_tz)
    start_at = start_at.astimezone(datetime.timezone.utc)
    
    dt_start_at = datetime.datetime.fromtimestamp(
        answer.timestamp,
        tz=datetime.timezone.utc
    )
    print("start_at",start_at, start_at.tzinfo)
    print("dt_start_at",dt_start_at, dt_start_at.tzinfo)
    
    elapsed = int(
            (dt_start_at - start_at).total_seconds() * 1000
        )
    if elapsed > 10_000:
       raw_result = save_answer(answer.questionID,None,elapsed,dt_start_at)
    else:
        raw_result = save_answer(answer.questionID,answer.ansID,elapsed,dt_start_at)
    quest = quest_result(raw_result)
    if quest.life <= 0:
        print("遊戲結束")
        change_game_status(gameIds.UUID,"finish")
        return quest
        
    else:   
        return quest

def leave(gameUUID:str):
    change_game_status(gameUUID,"leaved")

def ser_result(gameUUID:str):
    return create_result(gameUUID)
