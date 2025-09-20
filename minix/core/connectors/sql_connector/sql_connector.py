from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy import create_engine, text
from minix.core.connectors import Connector

class SqlConnectorConfig:
    def __init__(
        self,
        username: str = None,
        password: str = None,
        host: str = None,
        port: int = None,
        database: str = None,
        driver: str = None,
        connect_timeout: int = 30,
        read_timeout: int = 60,
        write_timeout: int = 60,
        send_receive_timeout: int = 600,
        pool_timeout: int = 60,
        pool_recycle: int = 3600,
        tcp_keepalive: bool = True,
        compression: bool = True,
        max_execution_time: int = 600,
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

            self.connect_timeout = connect_timeout
            self.read_timeout = read_timeout
            self.write_timeout = write_timeout
            self.send_receive_timeout = send_receive_timeout
            self.pool_timeout = pool_timeout
            self.pool_recycle = pool_recycle
            self.tcp_keepalive = tcp_keepalive
            self.compression = compression
            self.max_execution_time = max_execution_time

    def read_from_dict(self, d: dict):
        self.username = d.get('username')
        self.password = d.get('password')
        self.host = d.get('host')
        self.port = d.get('port')
        self.database = d.get('database')
        self.driver = d.get('driver')

        self.connect_timeout = d.get('connect_timeout', 120)
        self.read_timeout = d.get('read_timeout', 120)
        self.write_timeout = d.get('write_timeout', 120)
        self.send_receive_timeout = d.get('send_receive_timeout', 600)
        self.pool_timeout = d.get('pool_timeout', 60)
        self.pool_recycle = d.get('pool_recycle', 3600)
        self.tcp_keepalive = d.get('tcp_keepalive', True)
        self.compression = d.get('compression', True)
        self.max_execution_time = d.get('max_execution_time', 600)

    def to_dict(self) -> dict:
        return {
            'username': self.username,
            'password': self.password,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'driver': self.driver,
            'connect_timeout': self.connect_timeout,
            'read_timeout': self.read_timeout,
            'write_timeout': self.write_timeout,
            'send_receive_timeout': self.send_receive_timeout,
            'pool_timeout': self.pool_timeout,
            'pool_recycle': self.pool_recycle,
            'tcp_keepalive': self.tcp_keepalive,
            'compression': self.compression,
            'max_execution_time': self.max_execution_time,
        }

    def __str__(self):
        return (
            f'username: {self.username}, password: ****, host: {self.host}, port: {self.port}, '
            f'database: {self.database}, driver: {self.driver}'
        )

class SqlConnector(Connector):
    def __init__(self, sql_connector_config: SqlConnectorConfig):
        cfg = sql_connector_config
        self.username = cfg.username
        self.password = cfg.password
        self.host = cfg.host
        self.port = cfg.port
        self.database = cfg.database
        self.driver = cfg.driver

        connect_args = self._build_connect_args(cfg)

        self.engine = create_engine(
            self.get_connection_string(self.driver),
            echo=False,
            pool_pre_ping=True,
            pool_recycle=cfg.pool_recycle,
            pool_timeout=cfg.pool_timeout,
            connect_args=connect_args,
        )

        if self.driver == 'clickhouse' and cfg.max_execution_time:
            with self.engine.connect() as conn:
                # applies for the current connection; pool_pre_ping may refresh conns,
                # so also set it at the start of work units when you open sessions.
                conn.execute(text(f"SET max_execution_time = {int(cfg.max_execution_time)}"))

        self.Session = scoped_session(
            sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        )

    def _build_connect_args(self, cfg: SqlConnectorConfig) -> dict:
        if self.driver == 'mysql':
            return {
                'connect_timeout': cfg.connect_timeout,
                'read_timeout': cfg.read_timeout,
                'write_timeout': cfg.write_timeout,
                # socket keepalive is enabled by default at OS level, but if you use
                # PyMySQL<1.1 there’s no explicit switch; rely on OS sysctls.
            }

        if self.driver == 'clickhouse':
            args = {
                'connect_timeout': cfg.connect_timeout,
                'send_receive_timeout': cfg.send_receive_timeout,
                'compression': cfg.compression,
            }
            try:
                if cfg.tcp_keepalive:
                    args['tcp_keepalive'] = True
            except Exception:
                pass
            return args

        raise Exception('Driver not supported')

    def get_session(self):
        if self.driver == 'clickhouse':
            conn = self.engine.connect()
            conn.execute(text("SET send_logs_level = 'warning'"))  # optional
            return self.Session(bind=conn)
        return self.Session()

    def get_engine(self):
        return self.engine

    def get_connection_string(self, driver: str) -> str:
        if driver == 'mysql':
            return self.get_mysql_connection_string()
        elif driver == 'clickhouse':
            return self.clickhouse_connection_string()
        else:
            raise Exception('Driver not supported')

    def get_mysql_connection_string(self) -> str:
        return f'mysql+pymysql://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}'

    def clickhouse_connection_string(self) -> str:
        return f'clickhouse+native://{self.username}:{self.password}@{self.host}:{self.port}/{self.database}'
