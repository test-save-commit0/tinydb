"""
This module implements tables, the central place for accessing and manipulating
data in TinyDB.
"""
from typing import Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Union, cast, Tuple
from .queries import QueryLike
from .storages import Storage
from .utils import LRUCache
__all__ = 'Document', 'Table'


class Document(dict):
    """
    A document stored in the database.

    This class provides a way to access both a document's content and
    its ID using ``doc.doc_id``.
    """

    def __init__(self, value: Mapping, doc_id: int):
        super().__init__(value)
        self.doc_id = doc_id


class Table:
    """
    Represents a single TinyDB table.

    It provides methods for accessing and manipulating documents.

    .. admonition:: Query Cache

        As an optimization, a query cache is implemented using a
        :class:`~tinydb.utils.LRUCache`. This class mimics the interface of
        a normal ``dict``, but starts to remove the least-recently used entries
        once a threshold is reached.

        The query cache is updated on every search operation. When writing
        data, the whole cache is discarded as the query results may have
        changed.

    .. admonition:: Customization

        For customization, the following class variables can be set:

        - ``document_class`` defines the class that is used to represent
          documents,
        - ``document_id_class`` defines the class that is used to represent
          document IDs,
        - ``query_cache_class`` defines the class that is used for the query
          cache
        - ``default_query_cache_capacity`` defines the default capacity of
          the query cache

        .. versionadded:: 4.0


    :param storage: The storage instance to use for this table
    :param name: The table name
    :param cache_size: Maximum capacity of query cache
    """
    document_class = Document
    document_id_class = int
    query_cache_class = LRUCache
    default_query_cache_capacity = 10

    def __init__(self, storage: Storage, name: str, cache_size: int=
        default_query_cache_capacity):
        """
        Create a table instance.
        """
        self._storage = storage
        self._name = name
        self._query_cache: LRUCache[QueryLike, List[Document]
            ] = self.query_cache_class(capacity=cache_size)
        self._next_id = None

    def __repr__(self):
        args = ['name={!r}'.format(self.name), 'total={}'.format(len(self)),
            'storage={}'.format(self._storage)]
        return '<{} {}>'.format(type(self).__name__, ', '.join(args))

    @property
    def name(self) ->str:
        """
        Get the table name.
        """
        return self._name

    @property
    def storage(self) ->Storage:
        """
        Get the table storage instance.
        """
        return self._storage

    def insert(self, document: Mapping) ->int:
        """
        Insert a new document into the table.

        :param document: the document to insert
        :returns: the inserted document's ID
        """
        doc_id = self._get_next_id()
        self._update_table(lambda table: table.update({doc_id: document}))
        self.clear_cache()
        return doc_id

    def insert_multiple(self, documents: Iterable[Mapping]) ->List[int]:
        """
        Insert multiple documents into the table.

        :param documents: an Iterable of documents to insert
        :returns: a list containing the inserted documents' IDs
        """
        doc_ids = []
        def updater(table):
            for document in documents:
                doc_id = self._get_next_id()
                table[doc_id] = document
                doc_ids.append(doc_id)
        self._update_table(updater)
        self.clear_cache()
        return doc_ids

    def all(self) ->List[Document]:
        """
        Get all documents stored in the table.

        :returns: a list with all documents.
        """
        return [self.document_class(doc, self.document_id_class(doc_id))
                for doc_id, doc in self._read_table().items()]

    def search(self, cond: QueryLike) ->List[Document]:
        """
        Search for all documents matching a 'where' cond.

        :param cond: the condition to check against
        :returns: list of matching documents
        """
        if cond in self._query_cache:
            return self._query_cache[cond]

        docs = [doc for doc in self.all() if cond(doc)]
        self._query_cache[cond] = docs
        return docs

    def get(self, cond: Optional[QueryLike]=None, doc_id: Optional[int]=
        None, doc_ids: Optional[List]=None) ->Optional[Union[Document, List
        [Document]]]:
        """
        Get exactly one document specified by a query or a document ID.
        However, if multiple document IDs are given then returns all
        documents in a list.
        
        Returns ``None`` if the document doesn't exist.

        :param cond: the condition to check against
        :param doc_id: the document's ID
        :param doc_ids: the document's IDs(multiple)

        :returns: the document(s) or ``None``
        """
        if doc_id is not None:
            table = self._read_table()
            if doc_id in table:
                return self.document_class(table[doc_id], self.document_id_class(doc_id))
            return None
        
        if doc_ids is not None:
            docs = []
            table = self._read_table()
            for id in doc_ids:
                if id in table:
                    docs.append(self.document_class(table[id], self.document_id_class(id)))
            return docs if docs else None
        
        if cond is not None:
            docs = self.search(cond)
            return docs[0] if docs else None
        
        return None

    def contains(self, cond: Optional[QueryLike]=None, doc_id: Optional[int
        ]=None) ->bool:
        """
        Check whether the database contains a document matching a query or
        an ID.

        If ``doc_id`` is set, it checks if the db contains the specified ID.

        :param cond: the condition use
        :param doc_id: the document ID to look for
        """
        if doc_id is not None:
            return doc_id in self._read_table()
        
        return bool(self.search(cond)) if cond is not None else False

    def update(self, fields: Union[Mapping, Callable[[Mapping], None]],
        cond: Optional[QueryLike]=None, doc_ids: Optional[Iterable[int]]=None
        ) ->List[int]:
        """
        Update all matching documents to have a given set of fields.

        :param fields: the fields that the matching documents will have
                       or a method that will update the documents
        :param cond: which documents to update
        :param doc_ids: a list of document IDs
        :returns: a list containing the updated document's ID
        """
        updated_ids = []

        def updater(table):
            nonlocal updated_ids
            for doc_id, doc in table.items():
                if (doc_ids is None or doc_id in doc_ids) and (cond is None or cond(doc)):
                    if callable(fields):
                        fields(doc)
                    else:
                        doc.update(fields)
                    updated_ids.append(doc_id)

        self._update_table(updater)
        self.clear_cache()
        return updated_ids

    def update_multiple(self, updates: Iterable[Tuple[Union[Mapping,
        Callable[[Mapping], None]], QueryLike]]) ->List[int]:
        """
        Update all matching documents to have a given set of fields.

        :returns: a list containing the updated document's ID
        """
        pass

    def upsert(self, document: Mapping, cond: Optional[QueryLike]=None) ->List[
        int]:
        """
        Update documents, if they exist, insert them otherwise.

        Note: This will update *all* documents matching the query. Document
        argument can be a tinydb.table.Document object if you want to specify a
        doc_id.

        :param document: the document to insert or the fields to update
        :param cond: which document to look for, optional if you've passed a
        Document with a doc_id
        :returns: a list containing the updated documents' IDs
        """
        pass

    def remove(self, cond: Optional[QueryLike]=None, doc_ids: Optional[
        Iterable[int]]=None) ->List[int]:
        """
        Remove all matching documents.

        :param cond: the condition to check against
        :param doc_ids: a list of document IDs
        :returns: a list containing the removed documents' ID
        """
        pass

    def truncate(self) ->None:
        """
        Truncate the table by removing all documents.
        """
        pass

    def count(self, cond: QueryLike) ->int:
        """
        Count the documents matching a query.

        :param cond: the condition use
        """
        pass

    def clear_cache(self) ->None:
        """
        Clear the query cache.
        """
        pass

    def __len__(self):
        """
        Count the total number of documents in this table.
        """
        return len(self._read_table())

    def __iter__(self) ->Iterator[Document]:
        """
        Iterate over all documents stored in the table.

        :returns: an iterator over all documents.
        """
        for doc_id, doc in self._read_table().items():
            yield self.document_class(doc, self.document_id_class(doc_id))

    def _get_next_id(self):
        """
        Return the ID for a newly inserted document.
        """
        pass

    def _read_table(self) ->Dict[str, Mapping]:
        """
        Read the table data from the underlying storage.

        Documents and doc_ids are NOT yet transformed, as 
        we may not want to convert *all* documents when returning
        only one document for example.
        """
        pass

    def _update_table(self, updater: Callable[[Dict[int, Mapping]], None]):
        """
        Perform a table update operation.

        The storage interface used by TinyDB only allows to read/write the
        complete database data, but not modifying only portions of it. Thus,
        to only update portions of the table data, we first perform a read
        operation, perform the update on the table data and then write
        the updated data back to the storage.

        As a further optimization, we don't convert the documents into the
        document class, as the table data will *not* be returned to the user.
        """
        pass
