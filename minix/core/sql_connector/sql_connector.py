from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy import create_engine


class SqlConnectorConfig:
    def __init__(
            self,
            username: str = None,
            password: str = None,
            host: str = None,
            port: int = None,
            database: str = None,
            driver: str = None,
            config_dict: dict = None,
            read_from_dict: bool = False
    ):
        if read_from_dict:
            self.read_from_dict(config_dict)

        else:
            self.username = username
            self.password = password
            self.host = host
            self.port = port
            self.database = database
            self.driver = driver

    def read_from_dict(self, config_dict: dict):
        self.username = config_dict.get('username')
        self.password = config_dict.get('password')
        self.host = config_dict.get('host')
        self.port = config_dict.get('port')
        self.database = config_dict.get('database')
        self.driver = config_dict.get('driver')

    def to_dict(self) -> dict:
        return {
            'username': self.username,
            'password': self.password,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'driver': self.driver
        }

    def __str__(self):
        return f'username: {self.username}, password: {self.password}, host: {self.host}, port: {self.port}, database: {self.database}, driver: {self.driver}'


class SqlConnector:
    def __init__(
            self,
            sql_connector_config: SqlConnectorConfig
    ):
        self.username = sql_connector_config.username
        self.password = sql_connector_config.password
        self.host = sql_connector_config.host
        self.port = sql_connector_config.port
        self.database = sql_connector_config.database
        self.driver = sql_connector_config.driver
        self.engine = create_engine(
            self.get_connection_string(self.driver),
            echo=False,
            pool_pre_ping=True,
            pool_recycle=3600  # Optional: recycle after 1 hour (seconds)
        )
        self.Session = scoped_session(
            sessionmaker(
                bind=self.engine,
                autocommit=False,
                autoflush=False
            )
        )

    def get_session(self):
        return self.Session()

    def get_engine(self):
        return self.engine

    def get_connection_string(self, driver: str) -> str:
        if driver == 'mysql':
            return self.get_mysql_connection_string()
        else:
            raise Exception('Driver not supported')

    def get_mysql_connection_string(self) -> str:
        return f'mysql+pymysql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}'
