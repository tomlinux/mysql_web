# -*- coding: utf-8 -*-

import os, argparse, sys, time, datetime, subprocess, traceback

# xtrabackup备份脚本
# python bk_xtrabackup.py --host=192.168.11.101 --user=yangcg --password=yangcaogui --mode=2 --backup-dir=/opt/my_backup
# 备份周期是按照一个星期来的，星期天全量备份，其余增量备份
# 参数详解：
# --host
# --user
# --password
# --port
# --backup-dir:备份目录，需要指定一个不存在的目录才行
# --mode：备份模式，1代表全量，2代表全量+增量
# --backup-time：定时备份时间，默认值为14天，也就是只保存两周
# --expire-days：备份文件过期时间
# --stream：是否启用压缩，0代表不压缩，1代表使用xbstream的gzip压缩
#       0：不压缩
#       1：使用xbstream+gzip
#       2：使用tar+pigz

# 调用方式
# 可以放在crontab里面进行定时调用
# 也可以直接运行此文件让它在后台运行

# backup.log各个分割字段含义
# {0}:{1}:{2}:{3}:{4}:{5}:{6}:{7}
# 备份模式:备份路径:备份日志路径:备份开始时间:备份结束时间:备份日期:备份是否正常:备份目录名称

# 注意：好像xtrabackup打印的输出信息是错误输出，使用2>>，重定向竟然能成功

SUNDAY_INT = 6
FULL_BACKUP = 1
INCREMENT_BACKUP = 2
WRITE_FILE_COVER = "w"
WRITE_FILE_APPEND = "a"


def check_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, dest="host", help="mysql host")
    parser.add_argument("--user", type=str, dest="user", help="mysql user")
    parser.add_argument("--password", type=str, dest="password", help="mysql password")
    parser.add_argument("--port", type=int, dest="port", help="mysql port", default=3306)
    parser.add_argument("--backup-dir", type=str, dest="backup_dir", help="backup dir")
    parser.add_argument("--mode", type=int, dest="mode", help="backup mode", default=INCREMENT_BACKUP)
    parser.add_argument("--backup-time", type=str, dest="backup_time", help="help time", default="03:30")
    parser.add_argument("--expire-days", type=int, dest="expire_days", help="expire backup days", default=14)

    parser.add_argument("--stream", type=int, dest="stream", help="--stream", default=0)
    parser.add_argument("--ssh-user", type=str, dest="ssh_user", help="backup remote user", default="root")
    parser.add_argument("--ssh-host", type=str, dest="ssh_host", help="backup remote host")

    args = parser.parse_args()

    if not args.host or not args.user or not args.password or not args.port:
        print("[error]:Please input host or user or password or port.")
        sys.exit(1)

    if not args.backup_dir:
        print("[error]:Please input backup directory.")
        print(parser.print_usage())
        sys.exit(1)

    if (os.path.exists(args.backup_dir) == False):
        os.mkdir(args.backup_dir)

    if (args.mode != FULL_BACKUP and args.mode != INCREMENT_BACKUP):
        print("[error]:Backup mode value is 1 or 2.")
        print(parser.print_usage())
        sys.exit(1)

    args.backup_log_file_path = os.path.join(args.backup_dir, "backup.log")
    args.checkpoints_file_path = os.path.join(args.backup_dir, "xtrabackup_checkpoints")
    return args


# 备份主方法
def backup(args):
    print("start backup.")
    if (args.mode == FULL_BACKUP):
        full_backup(args)
    else:
        day_of_week = datetime.datetime.now().weekday()
        if (day_of_week == SUNDAY_INT):
            full_backup(args)
        else:
            increment_backup(args)
    remove_expire_backup_directory(args)
    print("backup complete ok.")


# 获取当前日期
def get_backup_date():
    return time.strftime('%Y-%m-%d', time.localtime(time.time()))


# 获取当前日期+时间
def get_current_time():
    return time.strftime('%Y-%m-%d_%H-%M-%S', time.localtime(time.time()))


# 全量备份
def full_backup(args):
    start_backup_time = get_current_time()
    backup_dir_name = "full_{0}".format(start_backup_time)
    full_backup_dir = os.path.join(args.backup_dir, backup_dir_name)
    if (os.path.exists(full_backup_dir) == False):
        os.mkdir(full_backup_dir)
    full_backup_log_path = os.path.join(args.backup_dir, "full_{0}.log".format(start_backup_time))
    command = "innobackupex --host={0} --user={1} --password='{2}' --port={3} --slave-info --no-timestamp {4} &> {5}"\
              .format(args.host, args.user, args.password, args.port, full_backup_dir, full_backup_log_path)
    result = subprocess.Popen(command, shell=True)
    result.wait()
    stop_backup_time = get_current_time()
    write_backup_log_file(args.backup_log_file_path, FULL_BACKUP, full_backup_dir, full_backup_log_path, start_backup_time, stop_backup_time, backup_dir_name)


# 增量备份，首先会找上一个备份
def increment_backup(args):
    last_line = read_backup_log_last_line(args.backup_log_file_path)
    if (last_line == None):
        return full_backup(args)

    last_line_values = last_line.split(":")
    if (len(last_line_values) > 0 and len(last_line_values) < 10):
        last_backup_dir = last_line_values[1]
        start_backup_time = get_current_time()
        backup_dir_name = "increment_{0}".format(start_backup_time)
        increment_backup_dir = os.path.join(args.backup_dir, backup_dir_name)
        if (os.path.exists(increment_backup_dir) == False):
            os.mkdir(increment_backup_dir)
        increment_backup_log_path = os.path.join(args.backup_dir, "increment_{0}.log".format(start_backup_time))
        command = "innobackupex --host={0} --user={1} --password='{2}' --port={3} --slave-info --no-timestamp --incremental --incremental-basedir={4} {5} &> {6}"\
                  .format(args.host, args.user, args.password, args.port, last_backup_dir, increment_backup_dir, increment_backup_log_path)
        result = subprocess.Popen(command, shell=True)
        result.wait()
        stop_backup_time = get_current_time()
        write_backup_log_file(args.backup_log_file_path, INCREMENT_BACKUP, increment_backup_dir, increment_backup_log_path, start_backup_time, stop_backup_time, backup_dir_name)
    else:
        full_backup(args)


# 增量备份，获取上一个备份的日志数据
def read_backup_log_last_line(file_path):
    lines = read_file_lines(file_path)
    if (lines != None and len(lines) > 0):
        return lines[-1]
    return None


# 备份会检查过期备份目录，节省磁盘空间
def remove_expire_backup_directory(args):
    current_time = datetime.datetime.now()
    for path in os.listdir(args.backup_dir):
        full_path = os.path.join(args.backup_dir, path)
        dir_or_file_time = datetime.datetime.fromtimestamp(os.path.getmtime(full_path))
        if ((current_time - dir_or_file_time).days > args.expire_days):
            if (os.path.isdir(full_path)):
                if (os.path.exists(full_path)):
                    os.rmdir(full_path)
                    print("remove dir {0} ok.".format(full_path))
            elif (os.path.isfile(full_path)):
                if (os.path.exists(full_path)):
                    os.remove(full_path)
                    print("remove file {0} ok.".format(full_path))


# 根据xtrabackup的输出日志判断备份是否正常
def check_backup_is_correct(xtrabackup_log_path):
    log_values = read_file_lines(xtrabackup_log_path)
    if (len(log_values) > 0):
        last_line = log_values[-1]
        if (last_line.find("completed OK") > 0):
            return 1
    return 0


# 增量备份，获取上一个备份的LSN
def get_xtrabackup_checkpoints(args):
    lines = read_file_lines(args.checkpoints_file_path)
    for value in lines:
        if (value.find("to_lsn") > 0):
            return value.split("=")[1].lstrip()
    return 0


# 读取文件所有的数据行
def read_file_lines(file_path):
    file = None
    try:
        file = open(file_path, "r")
        return file.readlines()
    except:
        traceback.print_exc()
        return None
    finally:
        if (file != None):
            file.close()


# 写入数据到备份日志文件中去
def write_backup_log_file(file_path, backup_mode, backup_dir, backup_log_path, start_time, stop_time, backup_dir_name):
    file = None
    try:
        log_value = "{0}:{1}:{2}:{3}:{4}:{5}:{6}:{7}\n".format(backup_mode,
                                                               backup_dir,
                                                               backup_log_path,
                                                               start_time,
                                                               stop_time,
                                                               get_backup_date(),
                                                               check_backup_is_correct(backup_log_path),
                                                               backup_dir_name)
        file = open(file_path, "a")
        file.write(log_value)
    finally:
        if (file != None):
            file.close()


# 后台运行代码
'''args = check_arguments()
while (True):
    current_time = time.strftime('%H:%M', time.localtime(time.time()))
    if (current_time == args.backup_time):
        backup(args)
    time.sleep(10)'''

# crontab运行代码
# backup(check_arguments())
