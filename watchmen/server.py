import json
import queue
import logging
import readline
import datetime
import argparse
import threading
from collections import OrderedDict

from flask import Flask, jsonify, request, render_template
from apscheduler.schedulers.blocking import BlockingScheduler

from watchmen.listener import is_single_gpu_totally_free, GPUInfo
from watchmen.client import ClientStatus, ClientModel, ClientCollection


logging.getLogger('apscheduler').setLevel(logging.ERROR)

app = Flask("watchmen.server")
gpu_queue = queue.Queue()
gpu_queue.put(GPUInfo())
client_queue = queue.Queue()
client_queue.put(ClientCollection())


@app.route("/gpu/<int:gpu_id>")
def get_single_gpu_status(gpu_id: int):
    status = ""
    msg = ""
    try:
        msg = is_single_gpu_totally_free(gpu_id)
        status = "ok"
    except ValueError as err:
        msg = str(err)
        status = "err"
    return jsonify(**{"status": status, "msg": msg})


@app.route("/gpus/<gpu_ids>")
def get_gpus_status(gpu_ids: str):
    status = "err"
    msg = ""
    detail = []
    try:
        gpu_ids = sorted(map(int, gpu_ids.split(',')))
        for gpu_id in gpu_ids:
            detail.append({
                "gpu": gpu_id,
                "status": is_single_gpu_totally_free(gpu_id)
            })
        if all(detail):
            msg = True
        else:
            msg = False
        status = "ok"
    except ValueError as err:
        msg = str(err)
        status = "err"
    return jsonify(**{"status": status, "msg": msg, "detail": detail})


@app.route("/client/ping", methods=["POST"])
def client_ping():
    client_info = ClientModel(**request.json)
    status = ""
    msg = ""
    client_id = client_info.id
    cc = client_queue.get()
    if client_id in cc:
        cc[client_id].last_request_time = datetime.datetime.now()
        status = "ok"
        msg = cc[client_id].status
    else:
        status = "err"
        msg = "cannot ping before register"
    client_queue.put(cc)
    return jsonify(**{"status": status, "msg": msg})


@app.route("/client/register", methods=["POST"])
def client_register():
    client_info = ClientModel(**request.json)
    status = ""
    msg = ""
    if len(client_info.gpus) <= 0:
        status = "err"
        msg = "gpus must not be empty!"
    else:
        cc = client_queue.get()
        if client_info.id not in cc:
            client = ClientModel(
                id=client_info.id,
                status=ClientStatus.WAITING,
                last_request_time=datetime.datetime.now(),
                queue_num=len(cc.work_queue),
                gpus=client_info.gpus,
            )
            cc.work_queue[client.id] = client
            status = "ok"
        else:
            status = "err"
            msg = f"client_id: {client_info.id} has been registered!"
        client_queue.put(cc)
    return jsonify(**{"status": status, "msg": msg})


@app.route("/show/work", methods=["GET"])
def show_work():
    status = ""
    msg = ""
    cc = client_queue.get()
    try:
        status = "ok"
        msg = [x.dict() for x in cc.work_queue.values()]
    except Exception as err:
        status = "err"
        msg = str(err)
    finally:
        client_queue.put(cc)
    return jsonify(**{"status": status, "msg": msg})


@app.route("/show/finished", methods=["GET"])
def show_finished():
    status = ""
    msg = ""
    cc = client_queue.get()
    try:
        status = "ok"
        msg = [x.dict() for x in cc.finished_queue.values()]
    except Exception as err:
        status = "err"
        msg = str(err)
    finally:
        client_queue.put(cc)
    return jsonify(**{"status": status, "msg": msg})


@app.route("/show/gpus", methods=["GET"])
def show_gpus():
    status = ""
    msg = ""
    gpu_info = gpu_queue.get()
    try:
        status = "ok"
        msg = gpu_info.gs.jsonify()
        msg["query_time"] = str(msg["query_time"])
    except Exception as err:
        status = "err"
        msg = str(err)
    finally:
        gpu_queue.put(gpu_info)
    return jsonify(**{"status": status, "msg": msg})


@app.route("/", methods=["GET"])
def index():
    gpu_info = show_gpus()
    gpu_msg = gpu_info.json["msg"]
    work_info = show_work()
    work_msg = work_info.json
    finished_info = show_finished()
    finished_msg = finished_info.json
    return render_template("index.html",
                           gpu_msg=gpu_msg,
                           work_msg=work_msg,
                           finished_msg=finished_msg)


def check_gpu_info():
    info = gpu_queue.get()
    info.new_query()
    gpu_queue.put(info)


def check_work(queue_timeout):
    cc = client_queue.get()
    marked_finished = []
    reserved_gpus = set() # whether there can be multiple `ok` in one scan
    queue_num = 0
    for client_id, client in cc.work_queue.items():
        time_delta = datetime.datetime.now() - client.last_request_time
        if time_delta.seconds > queue_timeout:
            if client.status != ClientStatus.OK:
                client.status = ClientStatus.TIMEOUT
            client.queue_num = -1 # invalid client
            marked_finished.append(client_id)
            continue
        client.queue_num = queue_num
        ok = False
        if client.status == ClientStatus.OK:
            reserved_gpus |= set(client.gpus)
        else:
            gpu_info = gpu_queue.get()
            try:
                ok = gpu_info.is_gpus_available(client.gpus)
            except IndexError as err:
                client.msg = str(err)
            except ValueError as err:
                client.msg = str(err)
            finally:
                gpu_queue.put(gpu_info)
        if ok and len(set(client.gpus) & reserved_gpus) <= 0:
            client.status = ClientStatus.OK
            reserved_gpus |= set(client.gpus)
        queue_num += 1

    for client_id in marked_finished:
        cc.mark_finished(client_id)
    client_queue.put(cc)


def check_finished(status_queue_keep_time):
    cc = client_queue.get()
    marked_delete_ids = []
    for client_id, client in cc.finished_queue.items():
        time_delta = datetime.datetime.now() - client.last_request_time
        if time_delta.hours >= status_queue_keep_time:
            marked_delete_ids.append(client_id)
    for client_id in marked_delete_ids:
        cc.finished_queue.pop(client_id)
    client_queue.put(cc)


def regular_check(request_interval, queue_timeout, status_queue_keep_time):
    scheduler = BlockingScheduler()
    scheduler.add_job(check_gpu_info,
                      trigger='interval',
                      seconds=request_interval,
                      next_run_time=datetime.datetime.now())
    scheduler.add_job(check_work,
                      trigger='interval',
                      seconds=request_interval*5,
                      args=(queue_timeout,),
                      next_run_time=datetime.datetime.now())
    scheduler.add_job(check_finished,
                      trigger='interval',
                      hours=status_queue_keep_time,
                      args=(status_queue_keep_time,),
                      next_run_time=datetime.datetime.now())
    scheduler.start()


def api_server(host, port):
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="host address for api server")
    parser.add_argument("--port", type=str, default=62333,
                        help="port for api server")
    parser.add_argument("--queue_timeout", type=int, default=60,
                        help="timeout for queue waiting (seconds)")
    parser.add_argument("--request_interval", type=int, default=1,
                        help="interval for gpu status requesting (seconds)")
    parser.add_argument("--status_queue_keep_time", type=int, default=48,
                        help="hours for keeping the client status")
    args = parser.parse_args()

    # thread 1: check gpu and client info regularly
    check_worker = threading.Thread(name="check",
                                    target=regular_check,
                                    args=(args.request_interval,
                                          args.queue_timeout,
                                          args.status_queue_keep_time),
                                    daemon=True)

    # thread 2: fastapi backend
    api_server_worker = threading.Thread(name="api",
                                         target=api_server,
                                         args=(args.host, args.port),
                                         daemon=True)

    check_worker.start()
    api_server_worker.start()

    in_str = ''
    while in_str != 'exit':
        in_str = input('`help` >')
        if in_str == 'help':
            print("show work: show working queue")
            print("show finished: show finished queue")
            print("show gpus: show gpu status")
            print("exit: exit server")
        elif in_str == "exit":
            break
        elif in_str == "show work":
            cc = client_queue.get()
            for cid in cc.work_queue:
                print(cc[cid])
            client_queue.put(cc)
        elif in_str == "show finished":
            cc = client_queue.get()
            for cid in cc.finished_queue:
                print(cc[cid])
            client_queue.put(cc)
        elif in_str == "show gpus":
            gpu_info = gpu_queue.get()
            gpu_info.gs.print_formatted()
            gpu_queue.put(gpu_info)
        else:
            print("Not understand orz")
