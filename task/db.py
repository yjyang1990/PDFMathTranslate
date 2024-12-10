import pymysql
from dotenv import load_dotenv
import os

load_dotenv()

def get_db_conn():
    return pymysql.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        user=os.getenv("DB_USERNAME"),
        password=os.getenv("DB_PASSWORD"),
        db=os.getenv("DB_DATABASE")
    )

def close_db_conn(conn):
    conn.close() 