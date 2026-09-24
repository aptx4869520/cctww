import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import *
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.cctv_validation import CCTVValidationError, validate_cctv
from backend.error import NoUsableCCTVError
from backend.service import create_game_session, create_quest_stream, create_question, leave, ranking, refresh_cctv_pool, search_question, send_answer, ser_result, sev_cctv_byid, sev_rancctv
from backend.schema import CCTV, Leave_data, Send_data, SignRequest

logger = logging.getLogger(__name__)
POOL_REFRESH_INTERVAL_SECONDS = 60


async def maintain_cctv_pool() -> None:
	while True:
		try:
			await asyncio.to_thread(refresh_cctv_pool)
		except asyncio.CancelledError:
			raise
		except Exception:
			logger.exception("CCTV pool refresh failed")
		await asyncio.sleep(POOL_REFRESH_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
	pool_task = asyncio.create_task(maintain_cctv_pool())
	try:
		yield
	finally:
		pool_task.cancel()
		with contextlib.suppress(asyncio.CancelledError):
			await pool_task


app =FastAPI(lifespan=lifespan)
FRONTEND_DIR = FilePath(__file__).resolve().parent / "frontend"


@app.exception_handler(NoUsableCCTVError)
@app.exception_handler(CCTVValidationError)
async def unusable_cctv_error(request: Request, exc: Exception):
	return JSONResponse(
		{
			"error": True,
			"msg": "目前沒有可用的 CCTV，請稍後再試",
			"message": "目前沒有可用的 CCTV，請稍後再試",
		},
		status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
	)


def snapshot_response(snapshot) -> Response:
	return Response(
		content=snapshot.image_bytes,
		media_type=snapshot.media_type,
		headers={"Cache-Control": "no-store"},
	)

app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

@app.get("/", include_in_schema=False)
async def index(request: Request):
	return FileResponse(FRONTEND_DIR / "index.html", media_type="text/html")

@app.get("/game", include_in_schema=False)
async def attraction(request: Request):
	return FileResponse(FRONTEND_DIR / "game.html", media_type="text/html")

@app.get("/result", include_in_schema=False)
async def booking(request: Request):
	return FileResponse(FRONTEND_DIR / "result.html", media_type="text/html")

# api
@app.post('/api/sign',tags=["/index"])
async def sign_in(sign:SignRequest):
	gameUUID  = create_game_session(sign.name,sign.email)
	return JSONResponse({"OK":True,"gameID":gameUUID},status_code=status.HTTP_201_CREATED)

@app.get('/api/rencctv',tags=["/index"])
async def get_rencctv():
	cctv = sev_rancctv(require_usable=True)
	return snapshot_response(validate_cctv(cctv))


@app.get('/api/cctv',tags=["/index"])
async def get_cctv(ID:int):
	cctv = sev_cctv_byid(ID)
	return snapshot_response(validate_cctv(cctv))

@app.get("/api/ranking",tags=["/index"])
async def get_ranking():
	rlist = ranking()
	return JSONResponse(
        content=jsonable_encoder({"ranking_list": rlist}),
        status_code=status.HTTP_200_OK
    )

@app.get("/api/game/question",tags=["/game"])
async def get_question(gameID:str):
	quest = search_question(gameID)
	if quest is None:
		quest = create_question(gameID,4)

	return JSONResponse(quest.model_dump(),status_code=status.HTTP_200_OK)

@app.get("/api/game/cctv",tags=["/game"])
async def get_game_cctv(UUID:str):
	snapshot = create_quest_stream(UUID)
	return snapshot_response(snapshot)

@app.post("/api/game/send",tags=["/game"])
async def send_ans(answer:Send_data):
	result = send_answer(answer)
	return JSONResponse(result.model_dump(),status_code=status.HTTP_200_OK)


@app.post("/api/game/leave",tags=["/game"])
async def leave_game(data:Leave_data):
	result = leave(data.gameID)
	return JSONResponse({"OK":True},status_code=status.HTTP_200_OK)

@app.post("/api/game/result",tags=["/game"])
async def send_result(gameID:str):
	result = ser_result(gameID)
	return JSONResponse(result.model_dump(),status_code=status.HTTP_200_OK)
