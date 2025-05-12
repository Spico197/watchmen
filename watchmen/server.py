import os
import sys
import queue
import logging
import readline  # noqa: F401
import datetime
import argparse
import threading
import secrets
from functools import wraps

from flask import Flask, jsonify, request, render_template, make_response, session
from flask.json.provider import DefaultJSONProvider
from apscheduler.schedulers.blocking import BlockingScheduler

from watchmen.listener import (
    is_single_gpu_totally_free,
    check_gpus_existence,
    check_req_gpu_num,
    GPUInfo,
)
from watchmen.client import ClientStatus, ClientMode, ClientModel, ClientCollection


apscheduler_logger = logging.getLogger("apscheduler")
apscheduler_logger.setLevel(logging.ERROR)
logger = logging.getLogger("common")
logger.setLevel(logging.INFO)
fmt = "[%(asctime)-15s]-%(levelname)s-%(filename)s-%(lineno)d-%(process)d: %(message)s"
datefmt = "%a %d %b %Y %H:%M:%S"
formatter = logging.Formatter(fmt, datefmt)
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(formatter)
logger.addHandler(stream_handler)

app = Flask("watchmen.server")
app.secret_key = os.environ.get("WATCHMEN_SECRET_KEY", secrets.token_hex(32))
gpu_queue = queue.Queue()
gpu_info = GPUInfo()
gpu_queue.put(1)
client_queue = queue.Queue()
cc = ClientCollection()
client_queue.put(1)

APP_PORT = None
AUTH_TOKEN = None
PID_FILE = ".watchmen_server.pid"
TOKEN_FILE = ".watchmen_server.token"


class CustomJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        try:
            if isinstance(obj, datetime.datetime):
                return obj.strftime("%Y-%m-%d %H:%M:%S")
            iterable = iter(obj)
        except TypeError:
            pass
        else:
            return list(iterable)
        return DefaultJSONProvider.default(self, obj)


app.json_provider_class = CustomJSONProvider


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


def generate_token():
    """Generate a random token."""
    return secrets.token_hex(16)  # 32 character hex string


def login_required(f):
    """Decorator to require authentication for a route."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not AUTH_TOKEN:
            return f(*args, **kwargs)  # No authentication required

        # Check session
        if session.get("authenticated"):
            return f(*args, **kwargs)

        # Check token in headers or query parameters
        token = request.headers.get("X-Auth-Token") or request.args.get("token")
        if token and token == AUTH_TOKEN:
            session["authenticated"] = True
            return f(*args, **kwargs)

        return jsonify({"status": "err", "msg": "Authentication required"}), 401

    return decorated_function


@app.route("/auth", methods=["POST"])
def authenticate():
    """Authenticate with token."""
    if not AUTH_TOKEN:
        return jsonify({"status": "ok", "msg": "No authentication required"})

    data = request.get_json()
    if not data or "token" not in data:
        return jsonify({"status": "err", "msg": "Token required"}), 400

    if data["token"] == AUTH_TOKEN:
        session["authenticated"] = True
        return jsonify({"status": "ok", "msg": "Authentication successful"})
    else:
        return jsonify({"status": "err", "msg": "Invalid token"}), 401


@app.route("/gpu/<int:gpu_id>")
@login_required
def get_single_gpu_status(gpu_id: int):
    status = ""
    msg = ""
    try:
        msg = is_single_gpu_totally_free(gpu_id)
        status = "ok"
    except ValueError as err:
        msg = str(err)
        status = "err"
    return jsonify({"status": status, "msg": msg})


@app.route("/gpus/<gpu_ids>")
@login_required
def get_gpus_status(gpu_ids: str):
    status = "err"
    msg = ""
    detail = []
    try:
        gpu_ids = sorted(map(int, gpu_ids.split(",")))
        for gpu_id in gpu_ids:
            detail.append({"gpu": gpu_id, "status": is_single_gpu_totally_free(gpu_id)})
        if all(detail):
            msg = True
        else:
            msg = False
        status = "ok"
    except ValueError as err:
        msg = str(err)
        status = "err"
    return jsonify({"status": status, "msg": msg, "detail": detail})


@app.route("/client/ping", methods=["POST"])
@login_required
def client_ping():
    client_info = ClientModel(**request.json)
    status = ""
    available_gpus = []
    msg = ""
    client_id = client_info.id
    if client_id in cc:
        cc[client_id].last_request_time = datetime.datetime.now()
        status = "ok"
        available_gpus = cc[client_id].available_gpus
        msg = cc[client_id].status
    elif client_id in cc.finished_queue:
        status = "ok"
        available_gpus = cc.finished_queue[client_id].available_gpus
        msg = cc.finished_queue[client_id].status
    else:
        status = "err"
        msg = "client not registered or has been cancelled"
    info = {"status": status, "available_gpus": available_gpus, "msg": msg}
    logger.info(f"client {client_id} ping: {info}")
    return jsonify(info)


@app.route("/client/register", methods=["POST"])
@login_required
def client_register():
    client_info = ClientModel(**request.json)
    status = ""
    msg = ""
    if len(client_info.gpus) <= 0:
        status = "err"
        msg = "gpus must not be empty!"
    elif not ClientMode.has_value(client_info.mode):
        status = "err"
        msg = f"mode {client_info.mode} is not supported"
    elif not check_gpus_existence(client_info.gpus):
        status = "err"
        msg = "check the gpus existence"
    elif client_info.mode == ClientMode.SCHEDULE and not check_req_gpu_num(
        client_info.req_gpu_num
    ):
        status = "err"
        msg = "`req_gpu_num` is not valid"
    else:
        if client_info.id not in cc:
            client = ClientModel(
                id=client_info.id,
                mode=client_info.mode,
                status=ClientStatus.WAITING,
                register_time=datetime.datetime.now(),
                last_request_time=datetime.datetime.now(),
                queue_num=len(cc.work_queue),
                gpus=client_info.gpus,
                req_gpu_num=client_info.req_gpu_num,
            )
            cc.work_queue[client.id] = client
            status = "ok"
        else:
            status = "err"
            msg = f"client_id: {client_info.id} has been registered!"
    return jsonify({"status": status, "msg": msg})


@app.route("/client/cancel", methods=["POST"])
@login_required
def client_cancel():
    status = ""
    msg = ""
    try:
        client_id = request.json.get("id")
        if client_id in cc:
            client = cc[client_id]
            if client.status == ClientStatus.WAITING:
                client.status = ClientStatus.CANCELLED
                cc.mark_finished(client_id)
                status = "ok"
                msg = f"Client {client_id} cancelled successfully"
            else:
                status = "err"
                msg = f"Client {client_id} is not waiting"
        else:
            status = "err"
            msg = f"Client {client_id} not found"
    except Exception as err:
        status = "err"
        msg = str(err)
    return jsonify({"status": status, "msg": msg})


@app.route("/show/work", methods=["GET"])
@login_required
def show_work():
    status = ""
    msg = ""
    try:
        status = "ok"
        msg = [x.dict() for x in cc.work_queue.values()]
    except Exception as err:
        status = "err"
        msg = str(err)
    return jsonify({"status": status, "msg": msg})


@app.route("/show/finished", methods=["GET"])
@login_required
def show_finished():
    status = ""
    msg = ""
    try:
        status = "ok"
        msg = [x.dict() for x in cc.finished_queue.values()]
    except Exception as err:
        status = "err"
        msg = str(err)
    return jsonify({"status": status, "msg": msg})


@app.route("/show/gpus", methods=["GET"])
@login_required
def show_gpus():
    status = ""
    msg = ""
    try:
        status = "ok"
        msg = gpu_info.gs.jsonify()
        msg["query_time"] = str(msg["query_time"])
    except Exception as err:
        status = "err"
        msg = str(err)
    return jsonify({"status": status, "msg": msg})


@app.route("/api", methods=["GET", "OPTIONS"])
@login_required
def api():
    if request.method == "OPTIONS":
        response = make_response()
    else:
        gpu_info = show_gpus()
        gpu_msg = gpu_info.json["msg"]
        work_info = show_work()
        work_msg = work_info.json["msg"]
        finished_info = show_finished()
        finished_msg = finished_info.json["msg"]
        response = jsonify(
            {"gpu": gpu_msg, "work_queue": work_msg, "finished_queue": finished_msg}
        )
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


@app.route("/", methods=["GET"])
def index():
    global APP_PORT
    is_authenticated = session.get("authenticated", False) or not AUTH_TOKEN
    auth_required = AUTH_TOKEN is not None
    return render_template(
        "index.html",
        port=APP_PORT,
        is_authenticated=is_authenticated,
        auth_required=auth_required,
    )


@app.route("/old", methods=["GET"])
@login_required
def old_index():
    gpu_info = show_gpus()
    gpu_msg = gpu_info.json["msg"]
    work_info = show_work()
    work_msg = work_info.json
    finished_info = show_finished()
    finished_msg = finished_info.json
    return render_template(
        "old_index.html", gpu_msg=gpu_msg, work_msg=work_msg, finished_msg=finished_msg
    )


def check_gpu_info():
    gpu_info.new_query()
    logger.info("check gpu info")


def check_work(queue_timeout):
    logger.info("regular check")
    marked_finished = []
    reserved_gpus = set()
    client_list = []
    queue_num = 0
    for client_id, client in cc.work_queue.items():
        time_delta = datetime.datetime.now() - client.last_request_time
        logger.info(
            f"client: {client.id}, time_delta.seconds: {time_delta.seconds}, time_delta: {time_delta}"
        )
        if time_delta.seconds > queue_timeout:
            if client.status != ClientStatus.READY:
                client.status = ClientStatus.TIMEOUT
            else:
                client.status = ClientStatus.OK
            # invalid client
            client.queue_num = -1
            marked_finished.append(client_id)
            continue
        client.queue_num = queue_num
        ok = False
        available_gpus = []
        if client.status == ClientStatus.READY:
            reserved_gpus |= set(client.available_gpus)
        else:
            try:
                if client.mode == "queue":
                    ok = gpu_info.is_gpus_available(client.gpus)
                    available_gpus = client.gpus
                elif client.mode == "schedule":
                    ok, available_gpus = gpu_info.is_req_gpu_num_satisfied(
                        client.gpus, client.req_gpu_num
                    )
                else:
                    raise RuntimeError(f"Not supported mode: {client.mode}")
            except IndexError as err:
                client.msg = str(err)
            except ValueError as err:
                client.msg = str(err)
            except RuntimeError as err:
                client.msg = str(err)

        client_list.append([client_id, client, ok, set(available_gpus)])
        queue_num += 1

    # post check and assignment, and make sure gpus of `ready` clients will not be assigned to the others
    for client_id, client, ok, available_gpu_set in client_list:
        if (
            ok
            and len(available_gpu_set) > 0
            and len(available_gpu_set & reserved_gpus) < 1
        ):
            client.status = ClientStatus.READY
            client.available_gpus = available_gpus
            reserved_gpus |= set(client.available_gpus)
            logger.info(
                f"client: {client.id} is ready, available gpus: {client.available_gpus}"
            )

    for client_id in marked_finished:
        logger.info(f"client {client.id} marked as finished, status: {client.status}")
        cc.mark_finished(client_id)


def check_finished(status_queue_keep_time):
    logger.info("check out-dated finished clients")
    marked_delete_ids = []
    for client_id, client in cc.finished_queue.items():
        delta = datetime.datetime.now() - client.last_request_time
        if (delta.days * 24 + delta.seconds / 3600) >= status_queue_keep_time:
            marked_delete_ids.append(client_id)
    for client_id in marked_delete_ids:
        cc.finished_queue.pop(client_id)
        logger.info(f"remove {client.id} from finished queue")


def regular_check(request_interval, queue_timeout, status_queue_keep_time):
    scheduler = BlockingScheduler(logger=apscheduler_logger)
    scheduler.add_job(
        check_gpu_info,
        trigger="interval",
        seconds=request_interval,
        next_run_time=datetime.datetime.now(),
    )
    scheduler.add_job(
        check_work,
        trigger="interval",
        seconds=request_interval * 5,
        args=(queue_timeout,),
        next_run_time=datetime.datetime.now(),
    )
    if status_queue_keep_time != -1:
        scheduler.add_job(
            check_finished,
            trigger="interval",
            hours=status_queue_keep_time,
            args=(status_queue_keep_time,),
            next_run_time=datetime.datetime.now(),
        )
    scheduler.start()


def api_server(host, port):
    global APP_PORT
    APP_PORT = port
    app.run(host=host, port=port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--host", type=str, default="0.0.0.0", help="host address for api server"
    )
    parser.add_argument("--port", type=str, default=62333, help="port for api server")
    parser.add_argument(
        "--queue_timeout",
        type=int,
        default=300,
        help="timeout for queue waiting (seconds)",
    )
    parser.add_argument(
        "--request_interval",
        type=int,
        default=1,
        help="interval for gpu status requesting (seconds)",
    )
    parser.add_argument(
        "--status_queue_keep_time",
        type=int,
        default=48,
        help=(
            "hours for keeping the client status. "
            "set `-1` to keep all clients' status"
        ),
    )
    parser.add_argument(
        "--token",
        type=str,
        default="",
        help="Authentication token for accessing the web interface. If empty, a token will be generated. Set to 'none' to disable authentication.",
    )
    args = parser.parse_args()

    # Handle token authentication
    if args.token.lower() == "none":
        AUTH_TOKEN = None
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)  # Remove token file if auth is disabled
        logger.info("Authentication disabled")
    else:
        # Check for token from command line, file, or generate a new one
        if args.token:
            AUTH_TOKEN = args.token
            save_token_to_file(AUTH_TOKEN)
        else:
            AUTH_TOKEN = load_token_from_file()
            if not AUTH_TOKEN:
                AUTH_TOKEN = generate_token()
                save_token_to_file(AUTH_TOKEN)

        logger.info(f"Authentication enabled with token: {AUTH_TOKEN}")
        logger.info(f"Token saved to {os.path.abspath(TOKEN_FILE)}")

    logger.info(f"Running at: {args.host}:{args.port}")
    logger.info(f"Current pid: {os.getpid()} > {PID_FILE}")
    with open(PID_FILE, "wt", encoding="utf-8") as fout:
        fout.write(f"{os.getpid()}")

    # daemon threads will end automaticly if the main thread ends
    # thread 1: check gpu and client info regularly
    check_worker = threading.Thread(
        name="check",
        target=regular_check,
        args=(args.request_interval, args.queue_timeout, args.status_queue_keep_time),
        daemon=True,
    )

    # thread 2: main server api backend
    api_server_worker = threading.Thread(
        name="api", target=api_server, args=(args.host, args.port), daemon=True
    )

    check_worker.start()
    logger.info("check worker started")
    api_server_worker.start()
    logger.info("api server started")

    while True:
        try:
            if not check_worker.is_alive():
                logger.error("check worker is not alive, server quit")
                raise RuntimeError("check worker is not alive, server quit")
            if not api_server_worker.is_alive():
                logger.error("api server worker is not alive, server quit")
                raise RuntimeError("api server worker is not alive, server quit")
        except RuntimeError:
            logger.error("runtime error, kill the server")
            break
        except KeyboardInterrupt:
            logger.error("keyboard interrupted, kill the server")
            break
    logger.error("bye")
