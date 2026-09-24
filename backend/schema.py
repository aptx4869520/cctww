from datetime import datetime
from decimal import Decimal
import enum
from typing import Literal

from pydantic import BaseModel, Field

class CCTV:
    def __init__(self, cctvID: str, cctv_name: str = None, stream_url: str = None, 
                 screenshot_url: str = None, subAuthorityCode: str = None, 
                 location_type: int = None, road_class: int = None, 
                 road_name: str = None, dir: str = None, mile: str = None, 
                 lon: Decimal = None, lat: Decimal = None, 
                 ID: int = None, create_at: datetime = None, update_at: datetime = None):
        
        self.ID = ID
        self.cctvID = cctvID
        self.cctv_name = cctv_name
        self.stream_url = stream_url
        self.screenshot_url = screenshot_url
        self.subAuthorityCode = subAuthorityCode
        self.location_type = location_type  # 里程位置資訊(enum對應到server)
        self.road_class = road_class
        self.road_name = road_name
        self.dir = dir
        self.mile = mile
        self.lon = Decimal(str(lon)) if lon is not None else None
        self.lat = Decimal(str(lat)) if lat is not None else None
        self.create_at = create_at
        self.update_at = update_at

    @classmethod
    def from_dict(cls, data: dict):
        """將 API 或前端傳來的 dict 快速轉成 CCTV 物件"""
        return cls(
            cctvID=data.get('cctvID'),
            cctv_name=data.get('cctv_name'),
            stream_url=data.get('stream_url'),
            screenshot_url=data.get('screenshot_url'),
            subAuthorityCode=data.get('subAuthorityCode'),
            location_type=data.get('location_type'),
            road_class=data.get('road_class'),
            road_name=data.get('road_name'),
            dir=data.get('dir'),
            mile=data.get('mile'),
            lon=data.get('lon'),
            lat=data.get('lat')
        )

    def to_tuple_for_insert(self) -> tuple:
        """轉成適合 mysql.connector 寫入的 tuple 格式 (排除自增 ID 與時間)"""
        return (
            self.cctvID, self.cctv_name, self.stream_url, self.screenshot_url,
            self.subAuthorityCode, self.location_type, self.road_class,
            self.road_name, self.dir, self.mile, self.lon, self.lat
        )

class SignRequest(BaseModel):
    name: str | None = None
    email: str | None = None

class Rank(BaseModel):
    id:int 
    name:str
    score:int
    total_time:int
    total_stage:int
    finish_at:datetime
    percent:str

class Raw_rank(BaseModel):
    name:str
    score:int
    total_time:int
    total_stage:int
    finish_at:datetime

class Option(BaseModel):
    id:int
    name:str
    
class Des(BaseModel):
    dir:Literal["N","E","W","S","'NE'","NW","SE","SW"]
    class_type:str
    name:str
    mile:str
class Question(BaseModel):
    questionID:str
    question_cctvUUID:str
    game_stage:int
    des:Des
    options:list[Option]
    life:int= Field(ge=0, le=3)

class Raw_question(BaseModel):
    questionUUID:str
    question_cctvintID:int
    game_stage:int
    options:list[Option]
class Road_class(enum.IntEnum):
    NATIONAL = 0
    PROVINCIAL_EXPRESSWAY = 1
    CITY_EXPRESSWAY = 2
    PROVINCIAL = 3
    COUNTY = 4
    TOWNSHIP = 5
    CITY = 6

class Raw_question_result(BaseModel):
    isRight:bool
    answer:int
    gameID:int
class Question_result(BaseModel):
    isRight:bool
    answer:int
    life:int

class Ids(BaseModel):
    ID:int
    UUID:str

class Send_data(BaseModel):
    questionID:str
    ansID:int|None
    timestamp:int

class Leave_data(BaseModel):
    gameID:str

class Result_Option(BaseModel):
    ID:int
    name:str
    cctvUUID:str|None = None
    cctvID: int|None = None
    isAns:bool = False

class Error_question(BaseModel):
    questionUUID:str
    question_cctvintID:int
    game_stage:int
    answerID:int 
    options:list[Result_Option]

class Result_data(BaseModel):
    total_time:int
    point:int
    error_questions:list[Error_question]


    