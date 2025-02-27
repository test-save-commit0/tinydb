"""
Contains the :class:`base class <tinydb.middlewares.Middleware>` for
middlewares and implementations.
"""
from typing import Optional
from tinydb import Storage


class Middleware:
    """
    The base class for all Middlewares.

    Middlewares hook into the read/write process of TinyDB allowing you to
    extend the behaviour by adding caching, logging, ...

    Your middleware's ``__init__`` method has to call the parent class
    constructor so the middleware chain can be configured properly.
    """

    def __init__(self, storage_cls) ->None:
        self._storage_cls = storage_cls
        self.storage: Storage = None

    def __call__(self, *args, **kwargs):
        """
        Create the storage instance and store it as self.storage.

        Usually a user creates a new TinyDB instance like this::

            TinyDB(storage=StorageClass)

        The storage keyword argument is used by TinyDB this way::

            self.storage = storage(*args, **kwargs)

        As we can see, ``storage(...)`` runs the constructor and returns the
        new storage instance.


        Using Middlewares, the user will call::

                                       The 'real' storage class
                                       v
            TinyDB(storage=Middleware(StorageClass))
                       ^
                       Already an instance!

        So, when running ``self.storage = storage(*args, **kwargs)`` Python
        now will call ``__call__`` and TinyDB will expect the return value to
        be the storage (or Middleware) instance. Returning the instance is
        simple, but we also got the underlying (*real*) StorageClass as an
        __init__ argument that still is not an instance.
        So, we initialize it in __call__ forwarding any arguments we receive
        from TinyDB (``TinyDB(arg1, kwarg1=value, storage=...)``).

        In case of nested Middlewares, calling the instance as if it was a
        class results in calling ``__call__`` what initializes the next
        nested Middleware that itself will initialize the next Middleware and
        so on.
        """
        self.storage = self._storage_cls(*args, **kwargs)
        return self

    def __getattr__(self, name):
        """
        Forward all unknown attribute calls to the underlying storage, so we
        remain as transparent as possible.
        """
        return getattr(self.__dict__['storage'], name)


class CachingMiddleware(Middleware):
    """
    Add some caching to TinyDB.

    This Middleware aims to improve the performance of TinyDB by writing only
    the last DB state every :attr:`WRITE_CACHE_SIZE` time and reading always
    from cache.
    """
    WRITE_CACHE_SIZE = 1000

    def __init__(self, storage_cls):
        super().__init__(storage_cls)
        self.cache = None
        self._cache_modified_count = 0

    def read(self):
        """
        Read data from cache if available, otherwise read from storage.
        """
        if self.cache is None:
            self.cache = self.storage.read()
        return self.cache

    def write(self, data):
        """
        Write data to cache and increment the modified count.
        Flush to storage if the write cache size is reached.
        """
        self.cache = data
        self._cache_modified_count += 1
        
        if self._cache_modified_count >= self.WRITE_CACHE_SIZE:
            self.flush()

    def flush(self):
        """
        Flush all unwritten data to disk.
        """
        if self.cache is not None:
            self.storage.write(self.cache)
            self._cache_modified_count = 0

    def close(self):
        """
        Flush the cache and close the storage.
        """
        self.flush()
        self.storage.close()
