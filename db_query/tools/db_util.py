import datetime
import logging
from typing import Optional, Union
from urllib import parse
from uuid import UUID

import pandas as pd
from pandas import Timestamp
from sqlalchemy import create_engine
from pymongo import MongoClient
from pymongo.errors import PyMongoError


class DbUtil:

    def __init__(self, db_type: str,
                 username: str, password: str,
                 host: str, port: Optional[str] = None,
                 database: Optional[str] = None,
                 properties: Optional[str] = None) -> None:
        self.db_type = db_type.lower()
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.database = database
        self.properties = properties

        if self.db_type == 'mongodb':
            self.client = self._create_mongo_client()
        else:
            self.engine = create_engine(self.get_url(), pool_size=100, pool_recycle=36)

    def get_driver_name(self):
        driver_name = self.db_type
        if self.db_type == 'mysql':
            driver_name = 'mysql+pymysql'
        elif self.db_type == 'oracle':
            driver_name = 'oracle+oracledb'
        elif self.db_type == 'postgresql':
            driver_name = 'postgresql+psycopg2'
        return driver_name

    def _create_mongo_client(self):
        """Create MongoDB client connection."""
        # MongoDB connection string format:
        # mongodb://[username:password@]host1[:port1][,...hostN[:portN]][/[database][?options]]
        username = parse.quote_plus(self.username)
        password = parse.quote_plus(self.password)
        host = parse.quote_plus(self.host)

        port_part = f":{self.port}" if self.is_not_empty(self.port) else ""
        auth_part = f"{username}:{password}@" if username and password else ""
        options_part = f"?{self.properties}" if self.is_not_empty(self.properties) else ""

        connection_string = f"mongodb://{auth_part}{host}{port_part}/{options_part}"
        logging.info(f"MongoDB connection string: {connection_string}")

        return MongoClient(connection_string)

    def get_url(self):
        '''
        Get url for SQL databases
        '''
        if self.db_type == 'mongodb':
            raise ValueError("get_url() should not be called for MongoDB connections")

        parsed_username = parse.quote_plus(self.username)
        parsed_password = parse.quote_plus(self.password)
        parsed_host = parse.quote_plus(self.host)
        url = f"{self.get_driver_name()}://{parsed_username}:{parsed_password}@{parsed_host}"
        if self.is_not_empty(self.port):
            url = f"{url}:{str(self.port)}"
        url = f"{url}/"
        if self.is_not_empty(self.database):
            parsed_database = parse.quote_plus(self.database)
            url = f"{url}{parsed_database}"
        if self.is_not_empty(self.properties):
            url = f"{url}?{self.properties}"
        logging.info(f"url: {url}")
        return url

    def run_query(self, query_sql: str) -> list[dict]:
        '''
        Run SQL Query for SQL databases or MongoDB query
        '''
        if self.db_type == 'mongodb':
            return self._run_mongo_query(query_sql)
        else:
            return self._run_sql_query(query_sql)

    def _run_sql_query(self, query_sql: str) -> list[dict]:
        '''Run query for SQL databases'''
        query_sql = query_sql.replace('%', '%%')
        df = pd.read_sql_query(sql=query_sql, con=self.engine, parse_dates="%Y-%m-%d %H:%M:%S")
        df = df.fillna('')
        records = []
        if len(df) > 0:
            records = df.to_dict(orient="records")
        for record in records:
            for key in record:
                if type(record[key]) is Timestamp:
                    record[key] = record[key].strftime('%Y-%m-%d %H:%M:%S')
                if type(record[key]) is datetime.date:
                    record[key] = record[key].strftime('%Y-%m-%d')
                if type(record[key]) is UUID:
                    record[key] = str(record[key])
        return records

    def _run_mongo_query(self, query: str) -> list[dict]:
        '''Run query for MongoDB'''
        try:
            # MongoDB queries are typically in JSON format
            # We'll expect the query to be a string representation of a JSON query
            import json
            query_dict = json.loads(query)

            if not isinstance(query_dict, dict):
                raise ValueError("MongoDB query must be a JSON object")

            if 'collection' not in query_dict:
                raise ValueError("MongoDB query must specify a 'collection'")

            collection_name = query_dict['collection']
            db = self.client[self.database] if self.database else self.client.get_database()
            collection = db[collection_name]

            # Extract query, projection, and options
            mongo_query = query_dict.get('query', {})
            projection = query_dict.get('projection', None)
            limit = query_dict.get('limit', 0)
            skip = query_dict.get('skip', 0)
            sort = query_dict.get('sort', None)

            cursor = collection.find(mongo_query, projection)

            if limit > 0:
                cursor = cursor.limit(limit)
            if skip > 0:
                cursor = cursor.skip(skip)
            if sort:
                cursor = cursor.sort(sort)

            records = list(cursor)

            # Convert MongoDB specific types to strings
            for record in records:
                if '_id' in record:
                    record['_id'] = str(record['_id'])

            return records

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON query: {str(e)}")
        except PyMongoError as e:
            raise Exception(f"MongoDB query error: {str(e)}")

    def test_sql(self):
        if self.db_type == 'mongodb':
            return json.dumps({
                "collection": "test_collection",
                "query": {},
                "limit": 1
            })
        elif self.db_type in {'mysql', 'postgresql'}:
            return "SELECT 1"
        elif self.db_type == 'oracle':
            return "SELECT 1 FROM DUAL"

    @staticmethod
    def is_not_empty(s: str):
        return s is not None and s.strip() != ""