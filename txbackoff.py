from twisted.internet import defer
from twisted.internet.task import deferLater
from twisted.internet import reactor, protocol
from twisted.python import log
from twisted.python import failure
from txjsonrpc.jsonrpclib import Fault
from txredisapi import Connection as RedisConnection
import mmh3
import binascii
from functools import wraps
from urlparse import urlparse
import time

class RedisConfig:
	config = None
	redis_client = None

	@classmethod
	def init(Config, config):
		Config.config = config
		return Config.connect_redis_client()

	@classmethod
	def _set_redis_client(Config, client):
		log.msg("connected to redis")
		Config.redis_client = client
		return defer.succeed(True)

	@classmethod
	def _fail_redis_client(Config, err):
		log.err(err)
		log.err("failing to connect to redis")
	
	@classmethod
	def connect_redis_client(Config):
		if Config.trying:
            redis_client_d = RedisConnection(
				Config.config["host"],
				Config.config["port"],
				reconnect = True
			)
			redis_client_d.addCallback(Config._set_redis_client)
			redis_client_d.addErrback(Config._fail_redis_client)
			return redis_client_d

class TimeoutError(Exception):
	pass

class RedisRateLimiter(object):
	def __init__(self, prefix, version, timeout=1, retry=0.1, retry_timeout=20):
		self.prefix = prefix
		self.version = version
		self.timeout = timeout
		self.retry = retry
		self.retry_timeout = retry_timeout

	def __call__(self, original_func):
		decorator = self
		@wraps(original_func)
		def wrappee(*args, **kwargs):
			cache_data_d = decorator.wait_and_return_data(
				original_func,
				*args,
				**kwargs
			)
			return cache_data_d
		return wrappee

	def wait_and_return_data(self, original_func, *args, **kwargs):
		def handle_lock_result(lock_result, my_start_time):
			if lock_result == 1:
				ignore_d = Config.redis_client.expire(
					self.key(*args, **kwargs),
					self.timeout
				)
				return original_func(*args, **kwargs)
			else:
				return deferLater(
					reactor,
					self.timeout,
					set_lock,
					my_start_time
				)

		def set_lock(my_start_time):
			if my_start_time + self.retry_timeout < time.time():
				raise TimeoutError()
			redis_d = Config.redis_client.setnx(
				self.key(*args, **kwargs),
				"nothing"
			)
			redis_d.addErrback(Config.handle_redis_error)
			redis_d.addCallback(handle_lock_result, my_start_time)
			return redis_d
		if self.should_ratelimit(*args, **kwargs):
			my_start_time = time.time()
			lock_d = set_lock(my_start_time)
			return lock_d
		else:
			return original_func(*args, **kwargs)

class BodyDecoder(Protocol):
	def __init__(self, finished):
		self.mybody = ''
		self.finished = finished
 
	def dataReceived(self, bytes):
		self.mybody += bytes
 
	def connectionLost(self, reason):
		self.finished.callback(self.mybody)

def generate_backoff_key(uri, extra_headers):
	return "backoff:" + binascii.b2a_base64(mmh3.hash_bytes(
		"/".join(
			[uri,
			_get_arguments_key(extra_headers),
		)
	)).strip()

def _get_arguments_key(kwargs):
	return ("|".join(
			[":".join([key, value]) for key, value in kwargs.iteritems()]
			)
		)

def backoff_http_request(
	uri,
	decoderclass=BodyDecoder,
	extra_headers={},
	backoff_key = None
):

	if not backoff_key:
		backoff_key = generate_backoff_key(uri, extra_headers)

	request_url = str(uri)

	def handle_error(error, *args):
		error.raiseException()

	def handle_http_response(response):
		if (response.code == 200):
			finishe_d = defer.Deferred()
			response.deliverBody(decoderclass(finishe_d))
			return finishe_d
		else:
			pickled_non200_response = pickle.dumps(response)
			redis_d = Config.redis_client.set(
				backoff_key,
				pickled_non200_response,
				expire = non200_timeout_seconds,
				only_if_not_exists = True
			)
			raise HTTPRequestError(response.code,
				"got code %s talking to a remote http server: %s" %
				(str(response.code), response.phrase))

	http_request_d = Core.http_agent.request(
		'GET',
		request_url,
		Headers(headers),
		None)

	pickle.loads(zlib.decompress(redis_result))

	http_request_d.addCallback(handle_http_response)
	http_request_d.addErrback(handle_error, request_url)
	#http_request_d.addErrback(log.err, uri)
	return http_request_d