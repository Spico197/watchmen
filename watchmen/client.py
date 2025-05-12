import time
import logging
import datetime
import getpass
import os
from enum import Enum
from typing import List, Optional
from collections import OrderedDict

import requests
from pydantic import BaseModel

from watchmen.listener import check_gpus_existence, check_req_gpu_num


logger = logging.getLogger("common")
TOKEN_FILE = ".watchmen_client.token"


class ClientStatus(str, Enum):
    WAITING = "waiting"
    TIMEOUT = "timeout"
    READY = "ready"
    OK = "ok"
    CANCELLED = "cancelled"


class ClientMode(str, Enum):
    QUEUE = "queue"
    SCHEDULE = "schedule"

    @classmethod
    def has_value(cls, value):
        return value in set(cls._member_map_.values())


class ClientModel(BaseModel):
    id: str  # identifier in string format
    # `queue` (wait for specific gpus) or `schedule` (schedule by the server automatically)
    mode: Optional[ClientMode] = ClientMode.QUEUE
    register_time: Optional[datetime.datetime] = None  # datetime.datetime
    last_request_time: Optional[datetime.datetime] = None  # datetime.datetime
    status: Optional[ClientStatus] = ClientStatus.WAITING  # `waiting`, `timeout`, `ok`
    queue_num: Optional[int] = 0  # queue number
    # `queue` mode: gpus for requesting to run on; `schedule` mode: available gpu scope.
    gpus: Optional[List[int]] = []
    msg: Optional[str] = ""  # error or status message
    req_gpu_num: Optional[int] = 0  # `schedule` mode: how many gpus are requested
    available_gpus: Optional[List[int]] = []


class ClientCollection(object):
    def __init__(self):
        self.work_queue = OrderedDict()  # only `ok` and `waiting`
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
        else:
            raise IndexError(f"index: {index} does not exist or has finished")

    def __contains__(self, index: str):
        return index in self.work_queue


def load_token_from_file():
    """Load authentication token from file if it exists."""
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            return f.read().strip()
    return None


def save_token_to_file(token):
    """Save authentication token to file."""
    with open(TOKEN_FILE, "w") as f:
        f.write(token)


class WatchClient(object):
    def __init__(
        self,
        id: str,
        gpus: List[int],
        server_host: str,
        server_port: int,
        mode: Optional[ClientMode] = ClientMode.QUEUE,
        req_gpu_num: Optional[int] = 0,
        timeout: Optional[int] = 60,
        token: Optional[str] = None,
    ):
        self.base_url = f"http://{server_host}:{server_port}"
        self.id = f"{getpass.getuser()}@{id}"
        if self._validate_gpus(gpus):
            self.gpus = gpus
        else:
            raise ValueError("Check the GPU existence")
        if not self._validate_mode(mode):
            raise ValueError(f"Check the mode: {mode}")
        self.mode = mode
        if self.mode == ClientMode.SCHEDULE:
            if not self._validate_req_gpu_num(req_gpu_num):
                raise ValueError(f"Check the `req_gpu_num`: {req_gpu_num}")
        self.req_gpu_num = req_gpu_num
        self.timeout = timeout

        # Handle token authentication
        self.token = token
        if not self.token:
            logger.info(f"No token provided, trying to load from file {TOKEN_FILE}")
            self.token = load_token_from_file()
        if self.token:
            logger.info(f"Dump token to file {TOKEN_FILE}")
            save_token_to_file(self.token)
        else:
            logger.info("No token provided, and no token file found")

    def _validate_gpus(self, gpus: List[int]):
        return check_gpus_existence(gpus)

    def _validate_mode(self, mode: ClientMode):
        return ClientMode.has_value(mode)

    def _validate_req_gpu_num(self, req_gpu_num: int):
        return check_req_gpu_num(req_gpu_num)

    def _get_headers(self):
        """Get request headers with authentication token if available."""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["X-Auth-Token"] = self.token
        return headers

    def register(self):
        data = {
            "id": self.id,
            "gpus": self.gpus,
            "mode": self.mode,
            "req_gpu_num": self.req_gpu_num,
        }
        result = requests.post(
            self.base_url + "/client/register",
            json=data,
            headers=self._get_headers(),
            timeout=self.timeout,
        ).json()
        if result["status"] != "ok":
            raise RuntimeError(f"err registering: {result['msg']}")

    def ping(self):
        data = {"id": self.id}
        result = requests.post(
            self.base_url + "/client/ping",
            json=data,
            headers=self._get_headers(),
            timeout=self.timeout,
        ).json()
        if result["status"] != "ok":
            raise RuntimeError(f"err registering: {result['msg']}")
        else:
            if result["msg"] == ClientStatus.WAITING:
                return False, result["available_gpus"]
            elif result["msg"] == ClientStatus.READY:
                return True, result["available_gpus"]
            elif result["msg"] == ClientStatus.OK:
                logger.warning("Status is OK, which has finished requesting GPUs.")
                return False, result["available_gpus"]
            elif result["msg"] == ClientStatus.TIMEOUT:
                raise RuntimeError("status changed to TIMEOUT")
            elif result["msg"] == ClientStatus.CANCELLED:
                raise RuntimeError("client has been cancelled")

    def wait(self):
        self.register()
        flag = False
        available_gpus = []
        while not flag:
            flag, available_gpus = self.ping()
            time.sleep(10)
        return available_gpus
