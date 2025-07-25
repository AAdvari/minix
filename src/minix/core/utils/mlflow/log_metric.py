import time
import mlflow


def log_metric(name: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            end_time = time.time()
            mlflow.log_metric(name, end_time - start_time)
            return result
        return wrapper
    return decorator