"""Opt-in, single-owner local passwords. Never stored in project snapshots.

The owner token remains an internal authority anchor for existing grants and
machine clients. Browsers only supply a username/password and receive the same
short-lived HttpOnly session used by the existing HTTP boundary.
"""
import fcntl
import hashlib
import json
import os
import re
import secrets
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .store import require

ITERATIONS = 600_000


class LocalAccounts:
    def __init__(self, filename):
        self.path = Path(filename)
        require(self.path.is_absolute(), '本地账号文件必须是绝对路径')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(not self.path.parent.is_symlink() and not self.path.parent.stat().st_mode & 0o077,
                '本地账号目录必须私有(0700)')
        self.dummy_salt = secrets.token_bytes(32)

    @contextmanager
    def locked(self):
        fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            require(not os.fstat(fd).st_mode & 0o077, '本地账号锁文件必须私有')
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def read(self):
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd) as f:
            require(not os.fstat(f.fileno()).st_mode & 0o077, '本地账号文件必须私有(0600)', 'authorization_required', 403)
            require(os.fstat(f.fileno()).st_size <= 4096, '本地账号文件无效', 'authorization_required', 403)
            try:
                record = json.load(f)
                valid = (record['version'] == 1 and record['iterations'] == ITERATIONS
                         and isinstance(record['username'], str) and re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', record['username'])
                         and len(bytes.fromhex(record['salt'])) == 32
                         and len(bytes.fromhex(record['password_hash'])) == 32)
            except (KeyError, ValueError, TypeError):
                valid = False
            require(valid, '本地账号文件无效；请由实例所有者检查', 'authorization_required', 403)
            return record

    def registration_open(self):
        with self.locked():
            return self.read() is None

    def register(self, username, password):
        require(isinstance(username, str) and re.fullmatch(r'[A-Za-z0-9_.-]{3,32}', username),
                '账号须为3–32位字母、数字、下划线、点或短横线')
        require(isinstance(password, str) and 8 <= len(password) <= 128, '密码须为8–128个字符')
        with self.locked():
            require(self.read() is None, '本地账号已注册，请直接登录', 'registration_closed', 409)
            salt = secrets.token_bytes(32)
            record = {'version': 1, 'username': username, 'iterations': ITERATIONS,
                      'salt': salt.hex(), 'password_hash': self.derive(password, salt).hex()}
            fd, name = tempfile.mkstemp(prefix='.account-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(record, f); f.write('\n'); f.flush(); os.fsync(f.fileno())
                os.replace(name, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(directory)
                finally: os.close(directory)
            finally:
                if os.path.exists(name): os.unlink(name)
            return self.identity(record)

    @staticmethod
    def derive(password, salt):
        return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, ITERATIONS)

    @staticmethod
    def identity(record):
        return hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()

    def verify(self, username, password):
        require(isinstance(username, str) and len(username) <= 128
                and isinstance(password, str) and len(password) <= 128,
                '账号或密码错误', 'unauthorized', 401)
        with self.locked():
            record = self.read()
        salt = bytes.fromhex(record['salt']) if record else self.dummy_salt
        candidate = self.derive(password, salt)
        require(record and secrets.compare_digest(candidate.hex(), record['password_hash'])
                and secrets.compare_digest(username.encode(), record['username'].encode()),
                '账号或密码错误', 'unauthorized', 401)
        return self.identity(record)

    def current(self, identity):
        with self.locked():
            record = self.read()
        return bool(record and secrets.compare_digest(self.identity(record), identity))
