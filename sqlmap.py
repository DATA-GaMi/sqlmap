#!/usr/bin/env python

"""
Copyright (c) 2006-2024 sqlmap developers (https://sqlmap.org/)
See the file 'LICENSE' for copying permission
"""

from __future__ import print_function

try:
    import sys

    sys.dont_write_bytecode = True

    try:
        __import__("lib.utils.versioncheck")  # this has to be the first non-standard import
    except ImportError:
        sys.exit(
            "[!] 检测到错误安装（缺少模块）。请访问“https://github.com/sqlmapproject/sqlmap/#installation”了解更多详细信息")

    import bdb
    import glob
    import inspect
    import json
    import logging
    import os
    import re
    import shutil
    import sys
    import tempfile
    import threading
    import time
    import traceback
    import warnings

    if "--deprecations" not in sys.argv:
        warnings.filterwarnings(action="ignore", category=DeprecationWarning)
    else:
        warnings.resetwarnings()
        warnings.filterwarnings(action="ignore", message="'crypt'", category=DeprecationWarning)
        warnings.simplefilter("ignore", category=ImportWarning)
        if sys.version_info >= (3, 0):
            warnings.simplefilter("ignore", category=ResourceWarning)

    warnings.filterwarnings(action="ignore", message="Python 2 不再受支持")
    warnings.filterwarnings(action="ignore", message=".*was already imported", category=UserWarning)
    warnings.filterwarnings(action="ignore", message=".*using a very old release", category=UserWarning)
    warnings.filterwarnings(action="ignore", message=".*default buffer size will be used", category=RuntimeWarning)
    warnings.filterwarnings(action="ignore", category=UserWarning, module="psycopg2")

    from lib.core.data import logger

    from lib.core.common import banner
    from lib.core.common import checkPipedInput
    from lib.core.common import checkSums
    from lib.core.common import createGithubIssue
    from lib.core.common import dataToStdout
    from lib.core.common import extractRegexResult
    from lib.core.common import filterNone
    from lib.core.common import getDaysFromLastUpdate
    from lib.core.common import getFileItems
    from lib.core.common import getSafeExString
    from lib.core.common import maskSensitiveData
    from lib.core.common import openFile
    from lib.core.common import setPaths
    from lib.core.common import weAreFrozen
    from lib.core.convert import getUnicode
    from lib.core.common import setColor
    from lib.core.common import unhandledExceptionMessage
    from lib.core.compat import LooseVersion
    from lib.core.compat import xrange
    from lib.core.data import cmdLineOptions
    from lib.core.data import conf
    from lib.core.data import kb
    from lib.core.datatype import OrderedSet
    from lib.core.enums import MKSTEMP_PREFIX
    from lib.core.exception import SqlmapBaseException
    from lib.core.exception import SqlmapShellQuitException
    from lib.core.exception import SqlmapSilentQuitException
    from lib.core.exception import SqlmapUserQuitException
    from lib.core.option import init
    from lib.core.option import initOptions
    from lib.core.patch import dirtyPatches
    from lib.core.patch import resolveCrossReferences
    from lib.core.settings import GIT_PAGE
    from lib.core.settings import IS_WIN
    from lib.core.settings import LAST_UPDATE_NAGGING_DAYS
    from lib.core.settings import LEGAL_DISCLAIMER
    from lib.core.settings import THREAD_FINALIZATION_TIMEOUT
    from lib.core.settings import UNICODE_ENCODING
    from lib.core.settings import VERSION
    from lib.parse.cmdline import cmdLineParser
    from lib.utils.crawler import crawl
except KeyboardInterrupt:
    errMsg = "user aborted"

    if "logger" in globals():
        logger.critical(errMsg)
        raise SystemExit
    else:
        import time

        sys.exit("\r[%s] [CRITICAL] %s" % (time.strftime("%X"), errMsg))


def modulePath():
    """
    This will get us the program's directory, even if we are frozen
    using py2exe
    """

    try:
        _ = sys.executable if weAreFrozen() else __file__
    except NameError:
        _ = inspect.getsourcefile(modulePath)

    return getUnicode(os.path.dirname(os.path.realpath(_)), encoding=sys.getfilesystemencoding() or UNICODE_ENCODING)


def checkEnvironment():
    try:
        os.path.isdir(modulePath())
    except UnicodeEncodeError:
        errMsg = "您的系统不能正确处理非 ASCII 路径。 "
        errMsg += "请将 sqlmap 的目录移动到其他位置"
        logger.critical(errMsg)
        raise SystemExit

    if LooseVersion(VERSION) < LooseVersion("1.0"):
        errMsg = "你的运行时环境（例如 PYTHONPATH）是 "
        errMsg += "损坏。请确保您没有运行 "
        errMsg += "较新版本的 sqlmap 带有针对较旧版本的运行脚本 "
        errMsg += "版本"
        logger.critical(errMsg)
        raise SystemExit

    # Patch for pip (import) environment
    if "sqlmap.sqlmap" in sys.modules:
        for _ in ("cmdLineOptions", "conf", "kb"):
            globals()[_] = getattr(sys.modules["lib.core.data"], _)

        for _ in (
                "SqlmapBaseException", "SqlmapShellQuitException", "SqlmapSilentQuitException",
                "SqlmapUserQuitException"):
            globals()[_] = getattr(sys.modules["lib.core.exception"], _)


def main():
    """
    Main function of sqlmap when running from command line.
    """

    try:
        dirtyPatches()
        resolveCrossReferences()
        checkEnvironment()
        setPaths(modulePath())
        banner()

        # Store original command line options for possible later restoration
        args = cmdLineParser()
        cmdLineOptions.update(args.__dict__ if hasattr(args, "__dict__") else args)
        initOptions(cmdLineOptions)

        if checkPipedInput():
            conf.batch = True

        if conf.get("api"):
            # heavy imports
            from lib.utils.api import StdDbOut
            from lib.utils.api import setRestAPILog

            # Overwrite system standard output and standard error to write
            # to an IPC database
            sys.stdout = StdDbOut(conf.taskid, messagetype="stdout")
            sys.stderr = StdDbOut(conf.taskid, messagetype="stderr")

            setRestAPILog()

        conf.showTime = True
        dataToStdout("[!] 法律免责声明: %s\n\n" % LEGAL_DISCLAIMER, forceOutput=True)
        dataToStdout("[*] starting @ %s\n\n" % time.strftime("%X /%Y-%m-%d/"), forceOutput=True)

        init()

        if not conf.updateAll:
            # Postponed imports (faster start)
            if conf.smokeTest:
                from lib.core.testing import smokeTest
                os._exitcode = 1 - (smokeTest() or 0)
            elif conf.vulnTest:
                from lib.core.testing import vulnTest
                os._exitcode = 1 - (vulnTest() or 0)
            else:
                from lib.controller.controller import start
                if conf.profile:
                    from lib.core.profiling import profile
                    globals()["start"] = start
                    profile()
                else:
                    try:
                        if conf.crawlDepth and conf.bulkFile:
                            targets = getFileItems(conf.bulkFile)

                            for i in xrange(len(targets)):
                                target = None

                                try:
                                    kb.targets = OrderedSet()
                                    target = targets[i]

                                    if not re.search(r"(?i)\Ahttp[s]*://", target):
                                        target = "http://%s" % target

                                    infoMsg = "启动爬虫程序以查找目标 URL '%s' (%d/%d)" % (target, i + 1, len(targets))
                                    logger.info(infoMsg)

                                    crawl(target)
                                except Exception as ex:
                                    if target and not isinstance(ex, SqlmapUserQuitException):
                                        errMsg = "抓取时出现问题 '%s' ('%s')" % (target, getSafeExString(ex))
                                        logger.error(errMsg)
                                    else:
                                        raise
                                else:
                                    if kb.targets:
                                        start()
                        else:
                            start()
                    except Exception as ex:
                        os._exitcode = 1

                        if "无法发起新线程" in getSafeExString(ex):
                            errMsg = "无法启动新线程。请检查操作系统 (无) 限制"
                            logger.critical(errMsg)
                            raise SystemExit
                        else:
                            raise

    except SqlmapUserQuitException:
        if not conf.batch:
            errMsg = "user quit"
            logger.error(errMsg)

    except (SqlmapSilentQuitException, bdb.BdbQuit):
        pass

    except SqlmapShellQuitException:
        cmdLineOptions.sqlmapShell = False

    except SqlmapBaseException as ex:
        errMsg = getSafeExString(ex)
        logger.critical(errMsg)

        os._exitcode = 1

        raise SystemExit

    except KeyboardInterrupt:
        try:
            print()
        except IOError:
            pass

    except EOFError:
        print()

        errMsg = "exit"
        logger.error(errMsg)

    except SystemExit as ex:
        os._exitcode = ex.code or 0

    except:
        print()
        errMsg = unhandledExceptionMessage()
        excMsg = traceback.format_exc()
        valid = checkSums()

        os._exitcode = 255

        if any(_ in excMsg for _ in ("MemoryError", "Cannot allocate memory")):
            errMsg = "检测到内存耗尽"
            logger.critical(errMsg)
            raise SystemExit

        elif any(_ in excMsg for _ in ("No space left", "Disk quota exceeded", "Disk full while accessing")):
            errMsg = "输出设备上没有剩余空间"
            logger.critical(errMsg)
            raise SystemExit

        elif any(_ in excMsg for _ in ("The paging file is too small",)):
            errMsg = "没有剩余空间用于分页文件"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("Access is denied", "subprocess", "metasploit")):
            errMsg = "运行 Metasploit 时发生权限错误"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("Permission denied", "metasploit")):
            errMsg = "使用 Metasploit 时发生权限错误"
            logger.critical(errMsg)
            raise SystemExit

        elif "Read-only file system" in excMsg:
            errMsg = "输出设备以只读方式安装"
            logger.critical(errMsg)
            raise SystemExit

        elif "Insufficient system resources" in excMsg:
            errMsg = "检测到资源耗尽"
            logger.critical(errMsg)
            raise SystemExit

        elif "OperationalError: disk I/O error" in excMsg:
            errMsg = "输出设备上的 I/O 错误"
            logger.critical(errMsg)
            raise SystemExit

        elif "Violation of BIDI" in excMsg:
            errMsg = "无效 URL（违反 Bidi IDNA 规则 - RFC 5893）"
            logger.critical(errMsg)
            raise SystemExit

        elif "Invalid IPv6 URL" in excMsg:
            errMsg = "无效的 URL ('%s')" % excMsg.strip().split('\n')[-1]
            logger.critical(errMsg)
            raise SystemExit

        elif "_mkstemp_inner" in excMsg:
            errMsg = "访问临时文件时出现问题"
            logger.critical(errMsg)
            raise SystemExit

        elif any(_ in excMsg for _ in ("tempfile.mkdtemp", "tempfile.mkstemp", "tempfile.py")):
            errMsg = "无法写入临时目录 '%s'. " % tempfile.gettempdir()
            errMsg += "请确保您的磁盘未满，并且 "
            errMsg += "您有足够的写入权限 "
            errMsg += "创建临时文件和/或目录"
            logger.critical(errMsg)
            raise SystemExit

        elif "Permission denied: '" in excMsg:
            match = re.search(r"Permission denied: '([^']*)", excMsg)
            errMsg = "访问文件时发生权限错误 '%s'" % match.group(1)
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("twophase", "sqlalchemy")):
            errMsg = "请更新“sqlalchemy”包（>=1.1.11） "
            errMsg += "(Reference: 'https://qiita.com/tkprof/items/7d7b2d00df9c5f16fffe')"
            logger.critical(errMsg)
            raise SystemExit

        elif "invalid maximum character passed to PyUnicode_New" in excMsg and re.search(r"\A3\.[34]",
                                                                                         sys.version) is not None:
            errMsg = "请升级 Python 版本 (>= 3.5) "
            errMsg += "(Reference: 'https://bugs.python.org/issue18183')"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("scramble_caching_sha2", "TypeError")):
            errMsg = "请降级“PyMySQL”包（=<0.8.1） "
            errMsg += "(Reference: 'https://github.com/PyMySQL/PyMySQL/issues/700')"
            logger.critical(errMsg)
            raise SystemExit

        elif "must be pinned buffer, not bytearray" in excMsg:
            errMsg = "Python 解释器发生错误 "
            errMsg += "已在 2.7 版中修复。请进行相应更新 "
            errMsg += "(Reference: 'https://bugs.python.org/issue8104')"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("OSError: [Errno 22] Invalid argument: '", "importlib")):
            errMsg = "无法读取文件 '%s'" % extractRegexResult(
                r"OSError: \[Errno 22\] 无效参数: '(?P<result>[^']+)", excMsg)
            logger.critical(errMsg)
            raise SystemExit

        elif "hash_randomization" in excMsg:
            errMsg = "Python 解释器发生错误 "
            errMsg += "已在 2.7.3 中修复。请进行相应更新 "
            errMsg += "(Reference: 'https://docs.python.org/2/library/sys.html')"
            logger.critical(errMsg)
            raise SystemExit

        elif "AttributeError: unable to access item" in excMsg and re.search(r"3\.11\.\d+a", sys.version):
            errMsg = "当 sqlmap 使用 Python 3.11 的 ALPHA 版本运行时，存在一个已知问题。 "
            errMsg += "请降级到某个稳定的 Python 版本"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("Resource temporarily unavailable", "os.fork()", "dictionaryAttack")):
            errMsg = "运行多处理哈希破解时出现问题。 "
            errMsg += "请使用选项重新运行 '--threads=1'"
            logger.critical(errMsg)
            raise SystemExit

        elif "can't start new thread" in excMsg:
            errMsg = "创建新线程实例时出现问题. "
            errMsg += "请确保您没有运行太多进程"
            if not IS_WIN:
                errMsg += " (或者增加 'ulimit -u' 值)"
            logger.critical(errMsg)
            raise SystemExit

        elif "can't allocate read lock" in excMsg:
            errMsg = "常规套接字操作存在问题 "
            errMsg += "('%s')" % excMsg.strip().split('\n')[-1]
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("pymysql", "configparser")):
            errMsg = "检测到“pymsql”初始化错误（使用 Python3 依赖项）"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("ntlm", "socket.error, err", "SyntaxError")):
            errMsg = "检测到“python-ntlm”初始化错误（使用 Python2 语法）"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("drda", "to_bytes")):
            errMsg = "检测到“drda”初始化错误（使用 Python3 语法）"
            logger.critical(errMsg)
            raise SystemExit

        elif "'WebSocket' object has no attribute 'status'" in excMsg:
            errMsg = "检测到错误的 websocket 库"
            errMsg += " (Reference: 'https://github.com/sqlmapproject/sqlmap/issues/4572#issuecomment-775041086')"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("window = tkinter.Tk()",)):
            errMsg = "GUI 界面初始化存在问题 "
            errMsg += "('%s')" % excMsg.strip().split('\n')[-1]
            logger.critical(errMsg)
            raise SystemExit

        elif any(_ in excMsg for _ in ("unable to access item 'liveTest'",)):
            errMsg = "检测到不同版本的 sqlmap 文件的使用情况"
            logger.critical(errMsg)
            raise SystemExit

        elif any(_ in errMsg for _ in (": 9.9.9#",)):
            errMsg = "LOL xD"
            logger.critical(errMsg)
            raise SystemExit

        elif kb.get("dumpKeyboardInterrupt"):
            raise SystemExit

        elif any(_ in excMsg for _ in ("Broken pipe",)):
            raise SystemExit

        elif valid is False:
            errMsg = "code checksum failed (turning off automatic issue creation). "
            errMsg += "You should retrieve the latest development version from official GitHub "
            errMsg += "repository at '%s'" % GIT_PAGE
            logger.critical(errMsg)
            print()
            dataToStdout(excMsg)
            raise SystemExit

        elif any(_ in "%s\n%s" % (errMsg, excMsg) for _ in ("tamper/", "waf/", "--engagement-dojo")):
            logger.critical(errMsg)
            print()
            dataToStdout(excMsg)
            raise SystemExit

        elif any(_ in excMsg for _ in (
                "ImportError", "ModuleNotFoundError", "<frozen", "Can't find file for module", "SAXReaderNotAvailable",
                "<built-in function compile> returned NULL without setting an exception",
                "source code string cannot contain null bytes", "No module named", "tp_name field",
                "module 'sqlite3' has no attribute 'OperationalError'")):
            errMsg = "invalid runtime environment ('%s')" % excMsg.split("Error: ")[-1].strip()
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("SyntaxError: Non-ASCII character", ".py on line", "but no encoding declared")):
            errMsg = "invalid runtime environment ('%s')" % excMsg.split("Error: ")[-1].strip()
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("FileNotFoundError: [Errno 2] No such file or directory", "cwd = os.getcwd()")):
            errMsg = "invalid runtime environment ('%s')" % excMsg.split("Error: ")[-1].strip()
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("PermissionError: [WinError 5]", "multiprocessing")):
            errMsg = "there is a permission problem in running multiprocessing on this system. "
            errMsg += "Please rerun with '--disable-multi'"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("No such file", "_'")):
            errMsg = "corrupted installation detected ('%s'). " % excMsg.strip().split('\n')[-1]
            errMsg += "You should retrieve the latest development version from official GitHub "
            errMsg += "repository at '%s'" % GIT_PAGE
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("No such file", "sqlmap.conf", "Test")):
            errMsg = "you are trying to run (hidden) development tests inside the production environment"
            logger.critical(errMsg)
            raise SystemExit

        elif all(_ in excMsg for _ in ("HTTPNtlmAuthHandler", "'str' object has no attribute 'decode'")):
            errMsg = "软件包‘python-ntlm’与 "
            errMsg += "Python 3 (Reference: 'https://github.com/mullender/python-ntlm/pull/61')"
            logger.critical(errMsg)
            raise SystemExit

        elif "'DictObject' object has no attribute '" in excMsg and all(
                _ in errMsg for _ in ("(fingerprinted)", "(identified)")):
            errMsg = "枚举时出现问题。 "
            errMsg += "Because of a considerable chance of false-positive case "
            errMsg += "建议您使用 switch 重新运行 '--flush-session'"
            logger.critical(errMsg)
            raise SystemExit

        elif "database disk image is malformed" in excMsg:
            errMsg = "本地会话文件似乎格式不正确。请使用 '--flush-session'"
            logger.critical(errMsg)
            raise SystemExit

        elif "AttributeError: 'module' object has no attribute 'F_GETFD'" in excMsg:
            errMsg = "无效的运行事件 (\"%s\") " % excMsg.split("Error: ")[-1].strip()
            errMsg += "(Reference: 'https://stackoverflow.com/a/38841364' & 'https://bugs.python.org/issue24944#msg249231')"
            logger.critical(errMsg)
            raise SystemExit

        elif "bad marshal data (unknown type code)" in excMsg:
            match = re.search(r"\s*(.+)\s+ValueError", excMsg)
            errMsg = "你的一个 .pyc 文件已损坏%s" % (" ('%s')" % match.group(1) if match else "")
            errMsg += ". 请删除系统上的 .pyc 文件来修复此问题"
            logger.critical(errMsg)
            raise SystemExit

        for match in re.finditer(r'File "(.+?)", line', excMsg):
            file_ = match.group(1)
            try:
                file_ = os.path.relpath(file_, os.path.dirname(__file__))
            except ValueError:
                pass
            file_ = file_.replace("\\", '/')
            if "../" in file_:
                file_ = re.sub(r"(\.\./)+", '/', file_)
            else:
                file_ = file_.lstrip('/')
            file_ = re.sub(r"/{2,}", '/', file_)
            excMsg = excMsg.replace(match.group(1), file_)

        errMsg = maskSensitiveData(errMsg)
        excMsg = maskSensitiveData(excMsg)

        if conf.get("api") or not valid:
            logger.critical("%s\n%s" % (errMsg, excMsg))
        else:
            logger.critical(errMsg)
            dataToStdout("%s\n" % setColor(excMsg.strip(), level=logging.CRITICAL))
            createGithubIssue(errMsg, excMsg)

    finally:
        kb.threadContinue = False

        if (getDaysFromLastUpdate() or 0) > LAST_UPDATE_NAGGING_DAYS:
            warnMsg = "你的 sqlmap 版本已过时"
            logger.warning(warnMsg)

        if conf.get("showTime"):
            dataToStdout("\n[*] 结束于 @ %s\n\n" % time.strftime("%X /%Y-%m-%d/"), forceOutput=True)

        kb.threadException = True

        if kb.get("tempDir"):
            for prefix in (
                    MKSTEMP_PREFIX.IPC, MKSTEMP_PREFIX.TESTING, MKSTEMP_PREFIX.COOKIE_JAR, MKSTEMP_PREFIX.BIG_ARRAY):
                for filepath in glob.glob(os.path.join(kb.tempDir, "%s*" % prefix)):
                    try:
                        os.remove(filepath)
                    except OSError:
                        pass

            if not filterNone(filepath for filepath in glob.glob(os.path.join(kb.tempDir, '*')) if not any(
                    filepath.endswith(_) for _ in (".lock", ".exe", ".so", '_'))):  # ignore junk files
                try:
                    shutil.rmtree(kb.tempDir, ignore_errors=True)
                except OSError:
                    pass

        if conf.get("hashDB"):
            conf.hashDB.flush(True)
            conf.hashDB.close()  # NOTE: because of PyPy

        if conf.get("harFile"):
            try:
                with openFile(conf.harFile, "w+b") as f:
                    json.dump(conf.httpCollector.obtain(), fp=f, indent=4, separators=(',', ': '))
            except SqlmapBaseException as ex:
                errMsg = getSafeExString(ex)
                logger.critical(errMsg)

        if conf.get("api"):
            conf.databaseCursor.disconnect()

        if conf.get("dumper"):
            conf.dumper.flush()

        # short delay for thread finalization
        _ = time.time()
        while threading.active_count() > 1 and (time.time() - _) > THREAD_FINALIZATION_TIMEOUT:
            time.sleep(0.01)

        if cmdLineOptions.get("sqlmapShell"):
            cmdLineOptions.clear()
            conf.clear()
            kb.clear()
            conf.disableBanner = True
            main()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except SystemExit:
        raise
    except:
        traceback.print_exc()
    finally:
        # Reference: http://stackoverflow.com/questions/1635080/terminate-a-multi-thread-python-program
        if threading.active_count() > 1:
            os._exit(getattr(os, "_exitcode", 0))
        else:
            sys.exit(getattr(os, "_exitcode", 0))
else:
    # cancelling postponed imports (because of CI/CD checks)
    __import__("lib.controller.controller")
