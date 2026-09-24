
from datetime import datetime

import mysql.connector as sql

import json
import os 
from dotenv import load_dotenv
from pydantic import Field

from backend.error import DatabaseError
from backend.schema import CCTV, Error_question, Ids, Question, Question_result, Raw_question, Raw_question_result, Raw_rank, Result_Option, Result_data

load_dotenv()

config = {
    "host":os.getenv("DB_HOST"),
    "database":os.getenv("DB_NAME"),
    "user":os.getenv("DB_USER"),
    "password":os.getenv("DB_PW")
    }
cnxpool =  sql.pooling.MySQLConnectionPool(
    pool_name="cctww",
    pool_size=5,
    **config
    )

def get_cctv(id:int) -> CCTV:
    connect = cnxpool.get_connection()
    try:
        with connect.cursor(dictionary=True) as cur:
            query = "SELECT * FROM cctv WHERE ID = %s"
            cur.execute(query,(id,))
            row = cur.fetchone()
            if row is None:
                raise DatabaseError()
            return CCTV(**row)
    except DatabaseError:
        raise
    except Exception as e:
        print("get_cctv Error",e)
        raise DatabaseError() from e
    finally:
        connect.close()


def get_random_cctv() -> CCTV:
    connect = cnxpool.get_connection()
    try:
        with connect.cursor(dictionary=True) as cur:
            cur.execute("SELECT * FROM cctv ORDER BY RAND() LIMIT 1")
            row = cur.fetchone()
            if row is None:
                raise DatabaseError()
            return CCTV(**row)
    except DatabaseError:
        raise
    except Exception as e:
        print("get_random_cctv Error", e)
        raise DatabaseError() from e
    finally:
        connect.close()


def get_random_cctvs(limit: int) -> list[CCTV]:
    connect = cnxpool.get_connection()
    try:
        with connect.cursor(dictionary=True) as cur:
            cur.execute("SELECT * FROM cctv ORDER BY RAND() LIMIT %s", (limit,))
            return [CCTV(**row) for row in cur.fetchall()]
    except Exception as e:
        print("get_random_cctvs Error", e)
        raise DatabaseError() from e
    finally:
        connect.close()


def get_cctv_health_count() -> int:
    connect = cnxpool.get_connection()
    try:
        with connect.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM cctv_health")
            result = cur.fetchone()
            return int(result[0]) if result is not None else 0
    except Exception as e:
        print("get_cctv_health_count Error", e)
        raise DatabaseError() from e
    finally:
        connect.close()


def get_usable_cctv_candidates(checked_after: datetime, limit: int) -> list[CCTV]:
    connect = cnxpool.get_connection()
    try:
        with connect.cursor(dictionary=True) as cur:
            query = """
                SELECT c.*
                FROM cctv AS c
                INNER JOIN cctv_health AS h ON h.cctv_id = c.ID
                WHERE h.is_usable = TRUE
                  AND h.checked_at >= %s
                ORDER BY RAND()
                LIMIT %s
            """
            cur.execute(query, (checked_after, limit))
            return [CCTV(**row) for row in cur.fetchall()]
    except Exception as e:
        print("get_usable_cctv_candidates Error", e)
        raise DatabaseError() from e
    finally:
        connect.close()


def get_cctv_health_candidates(
    checked_before: datetime,
    limit: int,
    exclude_ids: set[int] | None = None,
) -> list[CCTV]:
    connect = cnxpool.get_connection()
    excluded = sorted(exclude_ids or set())
    try:
        with connect.cursor(dictionary=True) as cur:
            placeholders = ", ".join(["%s"] * len(excluded))
            exclusion = f"AND c.ID NOT IN ({placeholders})" if excluded else ""
            query = f"""
                WITH ranked_candidates AS (
                    SELECT
                        c.ID,
                        h.checked_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(
                                NULLIF(TRIM(c.road_name), ''),
                                CONCAT('__cctv_', c.ID)
                            )
                            ORDER BY h.checked_at IS NULL DESC, RAND()
                        ) AS road_rank
                    FROM cctv AS c
                    LEFT JOIN cctv_health AS h ON h.cctv_id = c.ID
                    WHERE (h.checked_at IS NULL OR h.checked_at < %s)
                    {exclusion}
                )
                SELECT c.*
                FROM ranked_candidates AS ranked
                INNER JOIN cctv AS c ON c.ID = ranked.ID
                ORDER BY
                    ranked.road_rank ASC,
                    ranked.checked_at IS NULL DESC,
                    RAND()
                LIMIT %s
            """
            cur.execute(query, (checked_before, *excluded, limit))
            return [CCTV(**row) for row in cur.fetchall()]
    except Exception as e:
        print("get_cctv_health_candidates Error", e)
        raise DatabaseError() from e
    finally:
        connect.close()


def get_game_question_cctvs(game_uuid: str) -> list[CCTV]:
    connect = cnxpool.get_connection()
    try:
        with connect.cursor(dictionary=True) as cur:
            query = """
                SELECT c.*
                FROM questions AS q
                INNER JOIN games AS g ON g.ID = q.gameID
                INNER JOIN cctv AS c ON c.ID = q.question_cctvID
                WHERE g.gameUUID = %s
                ORDER BY q.game_stage ASC
            """
            cur.execute(query, (game_uuid,))
            return [CCTV(**row) for row in cur.fetchall()]
    except Exception as e:
        print("get_game_question_cctvs Error", e)
        raise DatabaseError() from e
    finally:
        connect.close()


def save_cctv_health(
    cctv_id: int,
    is_usable: bool,
    quality_score: float | None,
    failure_reason: str | None,
    checked_at: datetime,
) -> None:
    connect = cnxpool.get_connection()
    try:
        with connect.cursor() as cur:
            query = """
                INSERT INTO cctv_health
                    (cctv_id, is_usable, quality_score, checked_at, failure_reason)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    is_usable = IF(
                        VALUES(checked_at) >= checked_at,
                        VALUES(is_usable),
                        is_usable
                    ),
                    quality_score = IF(
                        VALUES(checked_at) >= checked_at,
                        VALUES(quality_score),
                        quality_score
                    ),
                    failure_reason = IF(
                        VALUES(checked_at) >= checked_at,
                        VALUES(failure_reason),
                        failure_reason
                    ),
                    checked_at = GREATEST(checked_at, VALUES(checked_at))
            """
            cur.execute(
                query,
                (cctv_id, is_usable, quality_score, checked_at, failure_reason),
            )
        connect.commit()
    except Exception as e:
        connect.rollback()
        print("save_cctv_health Error", e)
        raise DatabaseError() from e
    finally:
        connect.close()

def create_user_and_game(name:str,email:str|None , uuid:str) ->list[Raw_rank]:
    cnt = cnxpool.get_connection()
    u_query_dict = {"name":name}
    if email is not None:
        u_query_dict["email"] = email
    u_query = f"INSERT INTO users({", ".join(u_query_dict.keys())}) VALUES ({",".join(["%s" for x in u_query_dict])})"

    try:
        with cnt.cursor() as cur:
            cur.execute(u_query,tuple(u_query_dict.values()))

            user_id = cur.lastrowid
            if user_id is None:
                raise DatabaseError()
            
            g_query="INSERT INTO games (gameUUID, userID) VALUES (%s,%s)"
            cur.execute(g_query,(uuid,user_id))
        cnt.commit()   
    except DatabaseError:
            cnt.rollback()
            raise
    except Exception as e:
        cnt.rollback()
        print("sign_in Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()

def get_ranking():
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor(dictionary=True) as cur:
            query =  """
            SELECT 
            users.name AS name , 
            COUNT(questions.ID) AS score, 
            games.total_time AS total_time, 
            games.current_stage AS current_stage,
            games.finish_at AS finish_at
            FROM games 
            INNER JOIN users
            ON  games.userID = users.ID AND users.email IS NOT NULL
            LEFT JOIN questions
            ON questions.gameID = games.ID AND questions.answerID = questions.user_answerID
            WHERE status = "finish" 
            GROUP BY
            games.ID,
            users.name,
            games.total_time,
            games.current_stage,
            games.finish_at
            ORDER BY score DESC, total_time ASC
            """
            cur.execute(query)
            result = cur.fetchall()
            rank_list = []
            for i in result:
                game = Raw_rank(
                    name=i["name"],
                    score=i["score"],
                    total_time=0 if i["total_time"] is None else i["total_time"],
                    total_stage=i["current_stage"],
                    finish_at=datetime.now() if i["finish_at"] is None else i["finish_at"]
                    )
                rank_list.append(game)

            return rank_list
    except Exception as e:
        print("get_ranking Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()

def get_life(gameUUID:str):
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            query = "SELECT life FROM games WHERE gameUUID = %s"
            cur.execute(query,(gameUUID,))
            result = cur.fetchone()

            if result is None:
                raise DatabaseError()

        return result[0]
    except DatabaseError:
        raise
    except Exception as e:
        print("get_life Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()     

def get_current_stage(gameUUID:str) ->int:
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            query = "SELECT current_stage FROM games WHERE gameUUID = %s"
            cur.execute(query,(gameUUID,))
            result = cur.fetchone()

            if result is None:
                raise DatabaseError()

        return result[0]
    except DatabaseError:
        raise
    except Exception as e:
        print("get_life Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close() 
        
def get_question_create_at(questionUUID:str) ->datetime:
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            query = """
            SELECT create_at 
            FROM questions 
            WHERE questionUUID = %s
            """
            cur.execute(query,(questionUUID,))
            result = cur.fetchone()

            if result is None:
                raise DatabaseError()

        return result[0]
    except DatabaseError:
        raise
    except Exception as e:
        print("get_life Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close() 

def get_gameID(gameUUID:str):
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            query = "SELECT ID FROM games WHERE gameUUID = %s"
            cur.execute(query,(gameUUID,))
            result = cur.fetchone()

            if result is None:
                raise DatabaseError()

        return result[0]
    except DatabaseError:
        raise
    except Exception as e:
        print("get_life Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()    
               
def save_question(gameID:int,question:Question,ansID:int,quest_cctvid:int):
    cnt = cnxpool.get_connection()
    options_json = json.dumps(
        [option.model_dump() for option in question.options],
        ensure_ascii=False
    )
    try:
        with cnt.cursor() as cur:
            query = """
            INSERT INTO questions
            (
            gameID, 
            game_stage,
            question_cctvID,
            options,
            answerID,
            questionUUID
            )
            VALUES
            (%s,%s,%s,%s,%s,%s)
            """
            payload= (
                gameID,
                question.game_stage,
                quest_cctvid,
                options_json,
                ansID,
                question.questionID
                )
            cur.execute(query,payload)
            cnt.commit()

    except Exception as e:
        print("save_question Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()          

def select_question(gameID:int,current_stage:int) -> Raw_question | None:
    cnt = cnxpool.get_connection()  
    try:
          with cnt.cursor(dictionary=True) as cur:
            query = """
                SELECT
                    questionUUID,
                    question_cctvID,
                    options,
                    game_stage
                FROM questions
                WHERE gameID = %s
                AND game_stage = %s
            """
            cur.execute(query,(gameID,current_stage))
            result = cur.fetchone()
            if result is None:
                return None
            
            question = Raw_question(
                questionUUID=result["questionUUID"],
                question_cctvintID=result["question_cctvID"],
                game_stage=result["game_stage"],
                options=json.loads(result["options"]),
                )
            return question
    except Exception as e:
        print("select_question Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()    


def delete_unusable_pending_question(gameID: int, current_stage: int) -> bool:
    """Remove only an unanswered current-stage question so it can be redrawn."""
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            query = """
                DELETE FROM questions
                WHERE gameID = %s
                AND game_stage = %s
                AND user_answerID IS NULL
                AND elapsed IS NULL
                AND answer_at IS NULL
            """
            cur.execute(query, (gameID, current_stage))
            deleted = cur.rowcount == 1
        cnt.commit()
        return deleted
    except Exception as e:
        cnt.rollback()
        print("delete_unusable_pending_question Error", e)
        raise DatabaseError() from e
    finally:
        cnt.close()

def save_answer(questionUUID:str,ansID:int|None,elapsed:int,answer_at:datetime) -> Raw_question_result:
    cnt = cnxpool.get_connection()

    try:
        with cnt.cursor() as cur:
            query = """
                UPDATE questions
                SET
                    user_answerID = %s,
                    elapsed = %s,
                    answer_at = %s
                WHERE questionUUID = %s
            """

            cur.execute(
                query,
                (ansID, elapsed, answer_at, questionUUID)
            )

            query = """
                SELECT
                    answerID,
                    user_answerID,
                    gameID
                FROM questions
                WHERE questionUUID = %s
            """

            cur.execute(query, (questionUUID,))
            answer = cur.fetchone()

            cnt.commit()

            return Raw_question_result(
                isRight=answer[0] == answer[1],
                answer=answer[0],
                gameID=answer[2]
            )

    except Exception as e:
        cnt.rollback()
        print("save_answer Error", e)
        raise DatabaseError() from e

    finally:
        cnt.close()
def quest_result(result:Raw_question_result) -> Question_result:
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            if not result.isRight :
                cur.execute("""
                UPDATE games 
                SET 
                life = GREATEST(life - 1, 0),
                current_stage = current_stage +  1 
                WHERE ID = %s
                """, (result.gameID,))
            else:
                cur.execute("""
                    UPDATE games 
                    SET current_stage = current_stage+  1 
                    WHERE ID = %s
                    """, (result.gameID,))
            cur.execute("SELECT life FROM games WHERE ID = %s",(result.gameID,))
            life = cur.fetchone()
            cnt.commit()
            return Question_result(
                isRight=result.isRight,
                answer=result.answer,
                life= life[0]
            )
    except Exception as e:
            cnt.rollback()
            print("quest_result Error",e)
            raise DatabaseError() from e
    finally:
        cnt.close()

def get_gameIDS_byquetionUID(questionUUID:str):

    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            query= """
                SELECT
                    g.ID,
                    g.gameUUID
                FROM games AS g
                JOIN questions AS q
                    ON q.gameID = g.ID
                WHERE q.questionUUID = %s
            """
            
            cur.execute(query,(questionUUID,))
            result = cur.fetchone()
            return Ids(
                ID=result[0],
                UUID=result[1]
            )
    except Exception as e:
        print("get_gameIDS_byquetionUID Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()

def change_game_status(gameUUID:str,status:str):

    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor() as cur:
            query= """
                UPDATE games
                SET status = %s
                WHERE gameUUID = %s
            """
            
            cur.execute(query,(status,gameUUID))
            cnt.commit()

    except Exception as e:
        print("chage_game_status Error",e)
        raise DatabaseError() from e
    finally:
        cnt.close()

def create_result(gameUUID:str) ->Result_data:
    cnt = cnxpool.get_connection()
    try:
        with cnt.cursor(dictionary=True) as cur:

            # 存total time
            time_query ="""
                SELECT COALESCE(SUM(elapsed), 0) AS total_time
                FROM questions
                WHERE gameID = (
                    SELECT ID
                    FROM games
                    WHERE gameUUID = %s
                )
            """
            cur.execute(time_query,(gameUUID,))
            total_time = cur.fetchone()["total_time"]

            # 算point
            point_query = """
                SELECT 
                SUM(id) as point
                FROM questions
                WHERE gameID = (SELECT ID FROM games WHERE gameUUID = %s )
                AND user_answerID = answerID
            """
            cur.execute(point_query,(gameUUID,))
            point = cur.fetchone()["point"]

            # 抓錯題
            err_quest_query = """
                SELECT
                    questionUUID,
                    question_cctvID,
                    options,
                    game_stage,
                    answerID
                FROM questions
                WHERE gameID = (
                    SELECT ID
                    FROM games
                    WHERE gameUUID = %s
                )
                AND (
                    user_answerID IS NULL
                    OR user_answerID <> answerID
                )
            """
            cur.execute(err_quest_query,(gameUUID,))
            rows = cur.fetchall()
            err_questions = [

                Error_question(
                    questionUUID=row["questionUUID"],
                    question_cctvintID=row["question_cctvID"],
                    game_stage=row["game_stage"]+1,
                    answerID=row["answerID"],
                    options=[
                        Result_Option(
                            **option,
                            isAns=(option["id"] == row["answerID"])
                        )
                        for option in json.loads(row["options"])
                    ]
                )
                for row in rows
            ]
            update_total_time_query = """
                UPDATE games SET total_time = %s WHERE gameUUID = %s
                """
            cur.execute(update_total_time_query,(total_time,gameUUID))
            cnt.commit()

            return Result_data(
                total_time=total_time / 1000,
                point=0 if point is None else point,
                error_questions=err_questions
            )
    except Exception as e:
        cnt.rollback()
        print("get_game_result Error", e)
        raise DatabaseError() from e

    finally:
        cnt.close()
