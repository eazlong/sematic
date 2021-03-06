# -*- coding:utf-8 -*-
from flask import Flask, jsonify, request, make_response, Response
import json, time
import tagger
import re
import os
import data_prepare as dp
import classifier_cnn as cc
import threading
import jieba
from werkzeug.datastructures import Headers
import logging
import sys
from traceback import format_tb
# from functools import wraps
handler = logging.FileHandler("log/semantic"+time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime())+".log", "w", "utf-8" )
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
                    datefmt='%a, %d %b %Y %H:%M:%S',
                    handlers = [handler])

app = Flask(__name__)

engines = {}
thread_pool = []

CLASSIFIER = 'classifier'
MAX_THREAD = 2


# def allow_cross_domain(fun):
#     @wraps(fun)
#     def wrapper_fun(*args, **kwargs):
#         rst = make_response(fun(*args, **kwargs))
#         rst.headers['Access-Control-Allow-Origin'] = '*'
#         rst.headers['Access-Control-Allow-Methods'] = 'PUT,GET,POST,DELETE'
#         allow_headers = "Referer,Accept,Origin,User-Agent"
#         rst.headers['Access-Control-Allow-Headers'] = allow_headers
#         return rst
#     return wrapper_fun


def data_dir(appid):
    return "data/" + appid + "/"


def data_file(appid, operation):
    return data_dir(appid) + operation + ".data"


def vocab_file(appid, operation):
    return data_dir(appid) + operation + ".vocabs"


def labels_file(appid):
    return data_dir(appid) + "labels.txt"


def load_labels(appid):
    lf = labels_file(appid)
    with open(lf, encoding='utf-8') as f:
        data = f.readlines()
        return [x.strip() for x in data]


# 装载用户字典


def load_dict(file):
    if not os.path.exists(file):
        return {}

    with open(file, 'r', encoding='utf-8') as f:
        data = f.read()
        if len(data) == 0:
            return {}
        return json.loads(data)


def train(data):
    try:
        json_data = json.loads(data.decode('utf-8'))
        appid = json_data['appid']
        train_data = json_data['data']
        if appid not in engines:
            engines[appid] = {}
        engines[appid]['reload'] = True
        logging.info("start train for %s" % appid)
        # ce
        base_dir = data_dir(appid)
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)

        # 创建标签文件，保存分类标签
        classifer_data = {}
        labels = list(train_data.keys())
        logging.info("labels %s" % labels)

        lf = labels_file(appid)
        with open(lf, "w", encoding='utf-8') as f:
            data = train_data.keys()
            result = map(lambda x: x.strip() + "\n", data)
            f.writelines(result)

        user_dict = load_dict(data_dir(appid) + "user_dict.txt")
        load_dict_for_jiaba(user_dict)

        # 创建分类后的数据文件
        data_list = []
        for d in train_data.items():
            operation = d[0]
            t_data = d[1]
            df = data_file(appid, operation)
            category = appid + "_" + operation
            logging.info("create tagger for %s" % category)
            data_list.append((df, category))

            with open(df, "w", encoding='utf-8') as f:
                for line in t_data:
                    f.write(line + "\r\n")
                    pattern = re.compile(r'\[.*?\]')
                    line = re.sub(pattern, '', line)
                    classifer_data[line] = operation

        for data in data_list:
            df, category = data
            vf = vocab_file(appid, category)
            dp.create_vocabulary_from_data_file(vf, df)
            step = 2
            t = tagger.Tagger(df, vf, category, data_dir(appid) + category, user_dict, step)
            t.train()

        vf = vocab_file(appid, CLASSIFIER)
        d = ".".join(list(classifer_data.keys()))
        lex, v = dp.create_vocabulary_from_data(vf, d, False)
        calssifier = cc.Classifier(v, appid, data_dir(appid) + 'classifier', labels)
        calssifier.train(classifer_data)
    except Exception as e:
        logging.error(e)
        logging.debug(format_tb(e.__traceback__))
        return False

    return True

# 为结巴分词载入词表


def load_dict_for_jiaba(dict):
    for d in dict:
        for v in dict[d]['dict'].items():
            if not v[0].isdigit():
                jieba.add_word(v[0])


@app.route('/dict', methods=['POST'])
def user_dict():
    data = request.get_data()
    json_data = json.loads(data.decode('utf-8'))
    appid = json_data['appid']
    user_dict = json_data['data']
    with open(data_dir(appid) + "user_dict.txt", 'w', encoding='utf-8') as f:
        f.write(json.dumps(user_dict))
    load_dict_for_jiaba(user_dict)
    return make_response(jsonify({'error': 'OK'}), 200)


@app.route('/login', methods=['POST'])
def login():
    logging.info(request.get_data().decode('utf-8'))
    name = request.form['name']
    pwd = request.form['password']

    with open("data/account.data", 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for l in lines:
            data = l.strip().split(' ')
            if data[0] == name and data[1] == pwd:
                appid = {}
                appid['appid'] = data[2]
                return jsonify(appid)
    return make_response(jsonify({'error': 'user name or password error'}), 500)


@app.route('/query', methods=['GET'])
def query():
    result = {}
    appid = request.args.get('appid')
    logging.info("get request form appid %s" % appid)
    path = "data/" + appid + "/"
    for _, _, files in os.walk(path):
        for file in files:
            (name, suffix) = os.path.splitext(file)
            logging.info("%s, %s" % (name, suffix))
            if suffix == '.data':
                with open(path + file, encoding='utf-8') as f:
                    l = f.readlines()
                    l = list(set(l))
                    result[name] = l
    user_dict = load_dict(data_dir(appid) + "user_dict.txt")
    result['dict'] = user_dict
    return jsonify(result)


@app.route('/train', methods=['POST'])
def traim_thread():
    if train(request.get_data()):
        return make_response(jsonify({'error': 'OK'}), 200)
    else:
        return make_response(jsonify({'error': 'train failed'}), 500)


def process_chinese_number(s):
    data = {'一': '1', '二': '2', '两': '2', '三': '3', '四': '4', '五': '5', '六': '6',
            '七': '7', '八': '8', '九': '9', '十': '10', '百': '00', '千': '000', '万': '0000'}
    for d in s:
        if d in data:
            logging.debug('**************%s' % (data[d]))
            s = s.replace(d, data[d])
    return s


def predict(json_data, result):
    try:
        appid = json_data['appid']
        sentence = json_data['sentence']
        sentence = process_chinese_number(sentence)
        e = engines[appid]
        vf = vocab_file(appid, CLASSIFIER)
        _, v = dp.build_vocabulary(vf)
        labels = load_labels(appid)
        # jieba.load_userdict(vf)

        user_dict = load_dict(data_dir(appid) + "user_dict.txt")
        load_dict_for_jiaba(user_dict)

        reload = False
        if 'reload' in e:
            reload = e['reload']
        if (CLASSIFIER not in e) or reload:
            e[CLASSIFIER] = cc.Classifier(v, appid, data_dir(appid) + 'classifier', labels)

        operation = e[CLASSIFIER].predict(sentence)

        if operation == '':
            return 'operation not gotten'

        logging.info("the operation is %s" % operation)

        category = appid + "_" + operation
        vf = vocab_file(appid, category)
        if (operation not in e) or reload:
            e[operation] = tagger.Tagger(data_file(appid, operation), vf,
                                         category, data_dir(appid) + category, user_dict)

        pairs = e[operation].determine(sentence)

    except Exception as e:
        logging.error(e)
        logging.debug(format_tb(e.__traceback__))
        return e

    result['appid'] = appid
    result['operation'] = operation
    result['data'] = pairs
    return result


def predict_thread(cond, args):
    while True:
        cond.acquire()
        logging.info("wait for singal!")
        cond.wait()
        predict(args[0], args[1])
        cond.notify()


@app.route('/predict', methods=['POST'])
def request_predict():
    logging.info("----------------------------------------------------------------")
    logging.info(request.data.decode('utf_8'))
    logging.info("----------------------------------------------------------------")
    data = request.get_data()
    json_data = json.loads(data.decode('utf-8'))
    appid = json_data['appid']

    if appid not in engines:
        engines[appid] = {}
    e = engines[appid]
    logging.info(appid)
    if 'thread' not in e:
        e['thread'] = thread_pool.pop()
        logging.info(len(thread_pool))

    result = {}
    e['thread'][1].acquire()
    e['thread'][2].extend([json_data, result])
    e['thread'][1].notify()
    logging.info("wait for result!")
    e['thread'][1].wait()
    j = jsonify(result)
    e['thread'][2].clear()

    logging.info("run success!")
    return j


class MyResponse(Response):
    def __init__(self, response=None, **kwargs):
        kwargs['headers'] = ''
        headers = kwargs.get('headers')
        # 跨域控制
        origin = ('Access-Control-Allow-Origin', '*')
        allow_headers = ('Access-Control-Allow-Headers',
                         'Referer, Accept, Origin, User-Agent, Content-Type')
        methods = ('Access-Control-Allow-Methods', 'HEAD, OPTIONS, GET, POST, DELETE, PUT')
        if headers:
            headers.add(*origin)
            headers.add(*methods)
            headers.add(*allow_headers)
        else:
            headers = Headers([origin, methods, allow_headers])
        kwargs['headers'] = headers
        return super().__init__(response, **kwargs)

if __name__ == "__main__":
    for i in range(MAX_THREAD):
        args = []
        cond = threading.Condition()
        t = threading.Thread(target=predict_thread, args=[cond, args])
        t.start()
        logging.info(cond)
        thread_pool.append((t, cond, args))
    app.response_class = MyResponse
    app.run(port=8003, host='0.0.0.0')
