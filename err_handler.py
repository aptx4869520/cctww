from fastapi.responses import JSONResponse
from fastapi import status
import backend.error
from main import app


@app.exception_handler(backend.error.DatabaseError)
async def sql_err(request, exc):
	 return JSONResponse(
            {
                "error": True,
                "message": "查詢發生錯誤"
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )