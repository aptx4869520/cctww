import requests
import xml.etree.ElementTree as ET

import mysql.connector as sql

import os 
from dotenv import load_dotenv

load_dotenv()

url="https://cctv-maintain.thb.gov.tw/opendataCCTVs.xml"

response = requests.get(url, verify=False)
connect = sql.connect(
    host=os.getenv("DB_HOST"),
    database=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PW")
)
if connect.is_connected():
    print("連線成功")

if response.status_code != 200:
    raise KeyError
    錯誤晚點寫
else:
    print(response)
    response.encoding ="utf-8"
    root = ET.fromstring(response.text)
    print("根節點標籤名稱：", root.tag)
    cctvs = root[4]
    print(cctvs.tag)
    cctv_list = []
    for i in cctvs:
        cctv = {}
        for data in i:
            cctv[data.tag.split("}", 1)[-1]] = data.text
        cctv_list.append(cctv)
    
    for k,v in cctv_list[0].items():
         print(k,v,type(v) )
    trans_list=[]
    for i in cctv_list:
        cctv = {}
        for k, v in i.items():
            match k:
                case "LocationType" | "RoadClass":
                    cctv[k] = int(v)
                case "PositionLon" | "PositionLat":
                    cctv[k] = float(v)
                case "LinkID" | "RoadID":
                    continue  # 遇到這兩個欄位，直接跳過不處理
                case _:
                    cctv[k] = v

        trans_list.append(cctv)
    for k,v in trans_list[0].items():
        print("trans_list",k,v,type(v) )
    insert_tuplelist = [
        (
            i["CCTVID"],
            i["SubAuthorityCode"],
            i["VideoStreamURL"],
            i["VideoImageURL"],
            i["LocationType"],
            i["PositionLon"],
            i["PositionLat"],
            i["SurveillanceDescription"],
            i["RoadName"],
            i["RoadClass"],
            i["RoadDirection"],
            i["LocationMile"],
        )
        for i in trans_list
    ]
    print("trans_list tuple", tuple(trans_list[0].values()))

    if connect.is_connected():
            cur = connect.cursor()
            try:
                query="""
                INSERT INTO cctv 
                (cctvID, 
                subAuthorityCode, 
                stream_url, 
                screenshot_url,
                location_type,
                lon, 
                lat,
                cctv_name,  
                road_name, 
                road_class,
                dir, 
                mile
                )
                VALUES
                (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """
                cur.executemany(query,insert_tuplelist)
                connect.commit()
                print(f"執行解果，增加了{cur.rowcount}項目")
            except Exception as e:
                connect.rollback()
                print(e)
            finally:
                connect.close()