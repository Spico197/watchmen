import time
import datetime
import getpass
from enum import Enum
from typing import List, Optional
from collections import OrderedDict

import requests
from pydantic import BaseModel

from watchmen.listener import gpus_existence_check


class ClientStatus(str, Enum):
    WAITING = "waiting"
    TIMEOUT = "timeout"
    OK = "ok"


class ClientModel(BaseModel):
    id: str # identifier in string format
    last_request_time: Optional[datetime.datetime] = None   # datetime.datetime
    status: Optional[ClientStatus] = ClientStatus.WAITING   # `waiting`, `timeout`, `ok`
    queue_num: Optional[int] = 0    # queue number
    gpus: Optional[List[int]] = []    # gpus for requesting to run on
    msg: Optional[str] = "" # error or status message


class ClientCollection(object):
    def __init__(self):
        self.work_queue = OrderedDict() # only `ok` and `waiting`
        self.finished_queue = OrderedDict()
    
    def mark_finished(self, client_id: str):
        self.finished_queue[client_id] = self.work_queue[client_id]
        self.work_queue.pop(client_id)

    def get_all_clients(self):
        all_clients = []
        all_clients.extend(list(self.finished_queue.values()))
        all_clients.sort(key=lambda x: x.last_request_time)
        all_clients.extend(list(self.work_queue.values()))
        return all_clients
    
    def __getitem__(self, index: str):
        if index in self.work_queue:
            return self.work_queue[index]
        elif index in self.finished_queue:
            return self.finished_queue[index]
        else:
            raise IndexError(f"index: {index} does not exist")

    def __contains__(self, index: str):
        return index in self.work_queue or index in self.finished_queue


class Client(object):
    def __init__(self, id: str, gpus: List[int],
                 server_host: str, server_port: int,
                 timeout: Optional[int] = 10):
        self.base_url = f"http://{server_host}:{server_port}"
        self.id = f"{getpass.getuser()}@{id}"
        self._validate_gpus(gpus)
        self.gpus = gpus
        self.timeout = timeout

    def _validate_gpus(self, gpus: List[int]):
        return gpus_existence_check(gpus)

    def register(self):
        data = {
            "id": self.id,
            "gpus": self.gpus
        }
        result = requests.post(self.base_url + "/client/register",
                               json=data, timeout=self.timeout).json()
        if result["status"] != "ok":
            raise RuntimeError(f"err registering: {result['msg']}")

    def ping(self):
        data = {
            "id": self.id
        }
        result = requests.post(self.base_url + "/client/ping",
                               json=data, timeout=self.timeout).json()
        if result["status"] != "ok":
            raise RuntimeError(f"err registering: {result['msg']}")
        else:
            if result["msg"] == ClientStatus.WAITING:
                return False
            elif result["msg"] == ClientStatus.OK:
                return True
            elif result["msg"] == ClientStatus.TIMEOUT:
                raise RuntimeError(f"status changed to TIMEOUT")

    def wait(self):
        self.register()
        flag = False
        while not flag:
            flag = self.ping()
            time.sleep(10)
