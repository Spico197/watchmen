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
            and (float(gpu.memory_used)/float(gpu.memory_total) <= 1e-3
                 or gpu.memory_used < 50):
        return True
    else:
        return False


def gpus_existence_check(gpus: List[int]):
    gs = GPUStatCollection.new_query()
    return all([gpu in gs.gpus for gpu in gpus])


class GPUInfo(object):
    def __init__(self):
        self.gpus = []
        self.new_query()

    def new_query(self):
        gs = GPUStatCollection.new_query()
        self.gpus = gs.gpus
        self.gs = gs
    
    def _is_totally_free(self, gpu_index: int):
        gpu = self.gpus[gpu_index]
        if len(gpu.processes) <= 0 \
                and gpu.utilization <= 10 \
                and (float(gpu.memory_used)/float(gpu.memory_total) <= 1e-3
                     or gpu.memory_used < 50):
            return True
        else:
            return False
    
    def is_gpus_available(self, gpus: List[int]):
        stts = []
        for gpu in gpus:
            stts.append(self._is_totally_free(gpu))
        return all(stts)

    def __getitem__(self, index: int):
        return self._is_totally_free(index)
    
    def __str__(self):
        tmp = self.gs.jsonify()
        tmp["query_time"] = str(tmp["query_time"])
        return json.dumps(tmp, indent=2, ensure_ascii=False)
