"""
Processors that execute code from code chunks
"""
import sys
import re
import os
import io
import copy

import ast
import shelve

from ..config import rcParams


class PwebProcessorBase(object):
    """ This is a base class that implements sequential chunk caching
    with simple change detection.  It considers a `cache=True|False`
    parameter per chunk.

    """

    def __init__(self, parsed, kernel, source, docmode,
                 figdir, outdir, always_inline=True):
        self.kernel = kernel
        self.parsed = parsed
        self.source = source
        self.documentationmode = docmode
        self.always_inline = always_inline

        self.figdir = figdir
        self.outdir = outdir
        self.executed = []

        self.cwd = os.path.dirname(os.path.abspath(source))
        self.basename = os.path.basename(os.path.abspath(source)).split(".")[0]
        self.pending_code = ""  # Used for multichunk splits

        self.cachedir = os.path.join(self.cwd, rcParams["cachedir"])

        if self.documentationmode:
            self.ensureDirectoryExists(self.cachedir)
            name = self.cachedir + "/" + self.basename + ".db"
            self.db = shelve.open(name)

    def run(self):
        # Create directory for figures
        self.ensureDirectoryExists(self.getFigDirectory())

        self.executed = []

        # Term chunk returns a list of dicts, this flattens the results
        for chunk in self.parsed:
            res = self._runcode(chunk)
            if isinstance(res, list):
                self.executed = self.executed + res
            else:
                self.executed.append(res)

        self.isexecuted = True

        self.close()

    def close(self):
        if self.db:
            self.db.close()

    def ensureDirectoryExists(self, figdir):
        if not os.path.isdir(figdir):
            os.mkdir(figdir)

    def getresults(self):
        #flattened = list(itertools.chain.from_iterable(self.executed))
        return copy.deepcopy(self.executed)

    def _runcode(self, chunk, session=None):
        """Execute code from a code chunk based on options
        """
        if chunk['type'] not in ['doc', 'code']:
            return chunk

        # Add defaultoptions to parsed options
        if chunk['type'] == 'code':
            defaults = rcParams["chunk"]["defaultoptions"].copy()
            defaults.update(chunk["options"])
            chunk.update(defaults)
            # This is a bit redundant,
            # it is added afterwards to support adding options as
            # metadata to notebooks
            chunk["options"] = defaults
            #del chunk['options']

        # Read the content from file or object
        if 'source' in chunk:
            source = chunk["source"]
            if os.path.isfile(source):
                file_source = io.open(source, "r",
                                      encoding='utf-8').read().rstrip()
                chunk["content"] = "\n" + file_source + "\n" + chunk['content']
            else:
                chunk_text = chunk["content"]  # Get the text from chunk
                # Get the module source using inspect
                module_text = self.loadstring(
                    "import inspect\nprint(inspect.getsource(%s))" % source)
                chunk["content"] = module_text.rstrip()
                if chunk_text.strip() != "":
                    chunk["content"] += "\n" + chunk_text

        if chunk['type'] == 'doc':
            chunk['content'] = self.loadinline(chunk['content'])
            return chunk

        if chunk['type'] == 'code':

            sys.stdout.write(
                "Processing chunk %(number)s named %(name)s from line %(start_line)s\n" %
                chunk)

            old_content = None
            if not chunk["complete"]:
                self.pending_code += chunk["content"]
                chunk['result'] = ''
                return chunk
            elif self.pending_code != "":
                old_content = chunk["content"]
                # Code from all pending chunks for running the code
                chunk["content"] = self.pending_code + old_content
                self.pending_code = ""

            if not chunk['evaluate']:
                chunk['result'] = ''
                return chunk

            self.pre_run_hook(chunk)

            if chunk['options'].get('cache', False) or\
                    rcParams['storeresults']:
                results = self._get_cached(chunk, self._term_wrap_chunks)
            else:
                results = self._term_wrap_chunks(chunk)

            if len(results) > 1:
                return(results)
            else:
                chunk, = results

        # After executing the code save the figure
        if chunk['fig']:
            chunk['figure'] = self.savefigs(chunk)

        if old_content is not None:
            # The code from current chunk for display
            chunk['content'] = old_content

        self.post_run_hook(chunk)

        return chunk

    def _get_cached(self, chunk, func):
        """ Check the cache for a chunk entry, compare the code in each,
        invalidate all chunks that follow when not equal.

        TODO: Determine, and use, dependency between chunks; only
        invalidate dependent chunks.
        TODO: Consider using a binary diff (e.g.
        https://pypi.python.org/pypi/bsdiff4/1.1.4).
        """

        chunk_id = str(chunk['number'])
        chunk_data = self.db.get(chunk_id, None)
        invalidate = False
        chunk_res = None

        this_ast_obj = ast.parse(chunk['content'])
        if chunk_data is None:
            # Using AST form for better syntax comparison (and the potential
            # for chunk dependency evaluation).
            chunk_data = {}
            chunk_data['ast_obj'] = this_ast_obj

            invalidate = True
        else:
            chunk_res = chunk_data.get('results', None)
            prev_ast_obj = chunk_data.get('ast_obj', None)

            # TODO: More efficient comparison?
            if chunk_res is None or\
                    ast.dump(this_ast_obj) != ast.dump(prev_ast_obj):
                chunk_data = {'ast_obj': this_ast_obj}
                invalidate = True

        if chunk_res is None:
            chunk_res = func(chunk)
            chunk_data['results'] = chunk_res

            # XXX TODO: Snapshot current session state.
            import ipdb
            ipdb.set_trace()  # XXX BREAKPOINT

            self.session_file = getattr(self, 'session_file',
                                        'chunk-{}'.format(chunk_id))
            chunk_data['session_filename'] = self.session_file
            self.loadstring("""
            import dill
            session_pickler = dill.dump_session({})
            """.format(self.session_file))

        else:
            chunk_res = chunk_data['results']

            # XXX TODO: Load previous session state snapshot.
            import ipdb
            ipdb.set_trace()  # XXX BREAKPOINT

            self.loadstring("""
            import dill
            session_unpickler = dill.load_session({})
            """.format(chunk_data['session_filename']))

        if invalidate:
            for k in self.db.keys():
                if int(k) > chunk_id:
                    self.db.pop(k, None)

            self.db[chunk_id] = chunk_data

        return chunk_res

    def _term_wrap_chunks(self, chunk):
        """
        XXX: The methods `loadterm` and `loadstring` are odd abstractions.
        Unless I'm missing something here this situation looks like it needs
        a `process / load_chunk`, then some multi-chunk logic wrapping that.
        """
        if chunk['term']:
            # Running in term mode can return a list of chunks
            chunks = []
            sources, results = self.loadterm(chunk['content'], chunk=chunk)
            n = len(sources)
            content = ""
            for i in range(n):
                if len(results[i]) == 0:
                    content += sources[i]
                else:
                    new_chunk = chunk.copy()
                    new_chunk["content"] = content + sources[i].rstrip()
                    content = ""
                    new_chunk["result"] = results[i]
                    chunks.append(new_chunk)
        else:
            chunk['result'] = self.loadstring(
                chunk['content'], chunk=chunk)
            chunks = [chunk]

        return chunks

    def post_run_hook(self, chunk):
        pass

    def pre_run_hook(self, chunk):
        pass

    def init_matplotlib(self):
        pass

    def savefigs(self, chunk):
        pass

    def getFigDirectory(self):
        return os.path.join(self.outdir, self.figdir)

    def load_shell(self, chunk):
        pass

    def loadstring(self, code, chunk=None):
        pass

    def loadterm(self, code_string, chunk=None):
        pass

    def load_inline_string(self, code_string):
        pass

    def loadinline(self, content):
        """Evaluate code from doc chunks using ERB markup"""
        # Flags don't work with ironpython
        splitted = re.split('(<%[\w\s\W]*?%>)', content)  # , flags = re.S)
        # No inline code
        if len(splitted) < 2:
            return content

        n = len(splitted)

        for i in range(n):
            elem = splitted[i]
            if not elem.startswith('<%'):
                continue
            if elem.startswith('<%='):
                code_str = elem.replace('<%=', '').replace('%>', '').lstrip()
                result = self.load_inline_string(code_str).strip()
                splitted[i] = result
                continue
            if elem.startswith('<%'):
                code_str = elem.replace('<%', '').replace('%>', '').lstrip()
                result = self.load_inline_string(code_str).strip()
                splitted[i] = result
        return ''.join(splitted)

    def add_echo(self, code_str):
        return 'print(%s),' % code_str

    def _hideinline(self, chunk):
        """Hide inline code in doc mode"""
        splitted = re.split('<%[\w\s\W]*?%>', chunk['content'])
        chunk['content'] = ''.join(splitted)
        return chunk
