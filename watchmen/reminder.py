import datetime
import hashlib
import hmac
import base64
import urllib
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, List

import requests


def send_email(
    host: str, # email host to login, like `smtp.163.com`
    port: int, # email port to login, like `25`
    user: str, # user email address for login, like `***@163.com`
    password: str, # password or auth code for login
    receiver: str, # receiver email address
    html_message: str, # content, html format supported
    subject: Optional[str] = "Notice" # email subject
):
    # set up the SMTP server
    s = smtplib.SMTP(host=host, port=port)
    s.starttls()
    s.login(user, password)

    msg = MIMEMultipart()       # create a message
    msg['From'] = user
    msg['To'] = receiver
    msg['Subject']="Notice"
    msg.attach(MIMEText(html_message, 'html'))
    s.send_message(msg)
    del msg
    # Terminate the SMTP session and close the connection
    s.quit()


def send_dingtalk_msg(
    dingtalk_user_mentions: List[str], # which user to mention, like `[183********]`
    dingtalk_secret: str, #like SEc1f****
    dingtalk_webhook_url: str, # like `https://oapi.dingtalk.com/robot/send?access_token=***`
    message: str # message content
):
    msg_template = {
        "msgtype": "text", 
        "text": {
            "content": message
        }, 
        "at": {
            "atMobiles": dingtalk_user_mentions,
            "isAtAll": False
        }
    }
    def _construct_encrypted_url():
        '''
        Visit https://ding-doc.dingtalk.com/doc#/serverapi2/qf2nxq for details
        '''
        timestamp = round(datetime.datetime.now().timestamp() * 1000)
        secret_enc = dingtalk_secret.encode('utf-8')
        string_to_sign = '{}\n{}'.format(timestamp, dingtalk_secret)
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        encrypted_url = dingtalk_webhook_url + '&timestamp={}'\
            .format(timestamp) + '&sign={}'.format(sign) 
        return encrypted_url
    postto = _construct_encrypted_url()
    requests.post(postto, json=msg_template)
