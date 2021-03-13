import json
from typing import List

from gpustat.core import GPUStatCollection


def is_single_gpu_totally_free(gpu_index: int):
    gs = GPUStatCollection.new_query()

    if not isinstance(gpu_index, int):
        raise ValueError(f"gpu_index: {gpu_index} is not int")
    if gpu_index >= len(gs.gpus) or gpu_index < 0:
        raise ValueError(f"gpu_index: {gpu_index} does not exist")

    gpu = gs.gpus[gpu_index]
    if len(gpu.processes) <= 0 \
            and gpu.utilization <= 10 \
            and (float(gpu.memory_used) / float(gpu.memory_total) <= 1e-3 or gpu.memory_used < 50):
        return True
    else:
        return False


def check_gpus_existence(gpus: List[int]):
    gs = GPUStatCollection.new_query()
    for gpu in gpus:
        try:
            gs.gpus[gpu]
        except KeyError:
            return False
    return True


def check_req_gpu_num(req_gpu_num: int):
    gs = GPUStatCollection.new_query()
    return req_gpu_num <= len(gs.gpus)


class GPUInfo(object):
    def __init__(self):
        self.gpus = []
        self.new_query()

    def new_query(self):
        gs = GPUStatCollection.new_query()
        self.gpus = gs.gpus
        self.gs = gs

    def _is_totally_free(self, gpu_index: int):
        self.new_query()
        gpu = self.gpus[gpu_index]
        if len(gpu.processes) <= 0 \
                and gpu.utilization <= 10 \
                and (float(gpu.memory_used) / float(gpu.memory_total) <= 1e-3 or gpu.memory_used < 50):
            return True
        else:
            return False

    def is_gpus_available(self, gpus: List[int]):
        stts = []
        for gpu in gpus:
            stts.append(self._is_totally_free(gpu))
        return all(stts)

    def get_available_gpus_in_scope(self, gpu_scope: List[int]):
        available_gpus = []
        for gpu in gpu_scope:
            if self._is_totally_free(gpu):
                available_gpus.append(gpu)
        return available_gpus

    def is_req_gpu_num_satisfied(self, gpu_scope: List[int], req_gpu_num: int):
        ok = False
        available_gpus = self.get_available_gpus_in_scope(gpu_scope)
        if req_gpu_num <= len(available_gpus):
            available_gpus = available_gpus[:req_gpu_num]
            ok = True
        return ok, available_gpus

    def __getitem__(self, index: int):
        return self._is_totally_free(index)

    def __str__(self):
        tmp = self.gs.jsonify()
        tmp["query_time"] = str(tmp["query_time"])
        return json.dumps(tmp, indent=2, ensure_ascii=False)
