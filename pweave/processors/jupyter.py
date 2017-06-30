# -*- coding: utf-8 -*-

import os
import textwrap
import logging

from jupyter_client.manager import start_new_kernel
from nbformat.v4 import output_from_msg
from IPython.core import inputsplitter

from .. import config
from .base import PwebProcessorBase
from . import subsnippets

try:
    from queue import Empty  # Python 3
except ImportError:
    from Queue import Empty  # Python 2

logger = logging.getLogger(__name__)

class JupyterProcessor(PwebProcessorBase):
    """Generic Jupyter processor, should work with any kernel"""

    def __init__(self, *args, **kwargs):
        super(JupyterProcessor, self).__init__(*args, **kwargs)

        self.extra_arguments = kwargs.get('extra_arguments', None)
        self.timeout = kwargs.get('timeout', -1)
        self.cwd = os.path.abspath(self.outdir)

    def open(self):
        super(JupyterProcessor, self).open()

        self.km, self.kc = start_new_kernel(
            kernel_name=self.kernel,
            extra_arguments=self.extra_arguments,
            stderr=open(os.devnull, 'w'),
            cwd=self.cwd)
        self.kc.allow_stdin = False

        logger.info("Started {} kernel ({}) in {}".format(
            self.kernel, self.km.connection_file, self.cwd))

    def close(self):
        super(JupyterProcessor, self).close()

        logger.info("Stopping {} kernel ({}) in {}".format(
            self.kernel, self.km.connection_file, self.cwd))

        self.kc.stop_channels()
        self.km.shutdown_kernel(now=True)

    def run_cell(self, src):
        cell = {}
        cell["source"] = src.lstrip()

        # TODO: Consider using `execute_interactive`.
        msg_id = self.kc.execute(src.lstrip())

        #self.log.debug("Executing cell:\n%s", cell.source)

        # wait for finish, with timeout
        while True:
            try:
                timeout = self.timeout
                if timeout < 0:
                    timeout = None
                msg = self.kc.shell_channel.get_msg(timeout=timeout)
            except Empty:
                # self.log.error(
                #    "Timeout waiting for execute reply (%is)." % self.timeout)
                if self.interrupt_on_timeout:
                    #self.log.error("Interrupting kernel")
                    self.km.interrupt_kernel()
                    break
                else:
                    try:
                        exception = TimeoutError
                    except NameError:
                        exception = RuntimeError
                    raise exception(
                        "Cell execution timed out, see log for details.")

            if msg['parent_header'].get('msg_id') == msg_id:
                break
            else:
                # not our reply
                continue

        outs = []

        while True:
            try:
                # We've already waited for execute_reply, so all output
                # should already be waiting. However, on slow networks, like
                # in certain CI systems, waiting < 1 second might miss messages.
                # So long as the kernel sends a status:idle message when it
                # finishes, we won't actually have to wait this long, anyway.
                msg = self.kc.iopub_channel.get_msg(timeout=4)
            except Empty:
                self.log.warn("Timeout waiting for IOPub output")
                if self.raise_on_iopub_timeout:
                    raise RuntimeError("Timeout waiting for IOPub output")
                else:
                    break
            if msg['parent_header'].get('msg_id') != msg_id:
                # not an output from our execution
                continue

            msg_type = msg['msg_type']
            #self.log.debug("output: %s", msg_type)
            content = msg['content']

            # print(msg)
            # set the prompt number for the input and the output
            if 'execution_count' in content:
                cell['execution_count'] = content['execution_count']

            if msg_type == 'status':
                if content['execution_state'] == 'idle':
                    break
                else:
                    continue
            elif msg_type == 'execute_input':
                continue
            elif msg_type == 'clear_output':
                outs = []
                continue
            elif msg_type.startswith('comm'):
                continue

            try:
                out = output_from_msg(msg)
            except ValueError:
                self.log.error("unhandled iopub msg: " + msg_type)
            else:
                outs.append(out)

        return outs

    def _kernel_eval(self, code_str, **kwargs):

        # Get rid of unnecessary indentations
        code_str_ = textwrap.dedent(code_str)

        eval_res = self.run_cell(code_str_)

        return eval_res

    # def _eval_output(self, code_str):
    #     r""" Format the raw kernel output to a basic chunk output.
    #     TODO: Why not use jupyter
    #     """
    #     from nbconvert import filters
    #     outputs = self._kernel_eval(code_str)
    #     result = ""
    #     for out in outputs:
    #         if out["output_type"] == "stream":
    #             result += out["text"]
    #         elif out["output_type"] == "error":
    #             result += filters.strip_ansi("".join(out["traceback"]))
    #         elif "text/plain" in out["data"]:
    #             result += out["data"]["text/plain"]
    #         else:
    #             result = ""
    #     return result

    def get_source(self, source):
        module_text = self._kernel_eval(
            "import inspect; print(inspect.getsource(%s))" % source)
        return module_text

class IPythonProcessor(JupyterProcessor):
    """Contains IPython specific functions"""

    def __init__(self, *args, **kwargs):
        super(IPythonProcessor, self).__init__(*args, **kwargs)

        if config.rcParams["usematplotlib"]:
            self.init_matplotlib()

    def init_matplotlib(self):
        self._kernel_eval(subsnippets.init_matplotlib)

    def pre_run_hook(self, chunk):
        f_size = """matplotlib.rcParams.update({"figure.figsize" : (%i, %i)})""" % chunk[
            "f_size"]
        f_dpi = """matplotlib.rcParams.update({"savefig.dpi" : %i})""" % chunk[
            "dpi"]
        self._kernel_eval("\n".join([f_size, f_dpi]))

    def loadterm(self, code_str, **kwargs):
        splitter = inputsplitter.IPythonInputSplitter()
        code_lines = code_str.lstrip().splitlines()
        sources = []
        outputs = []

        for line in code_lines:
            if splitter.push_accepts_more():
                splitter.push_line(line)
            else:
                code_str = splitter.source
                sources.append(code_str)
                _, out = self._kernel_eval(code_str)
                # print(out)
                outputs.append(out)
                splitter.reset()
                splitter.push_line(line)

        if splitter.source != "":
            code_str = splitter.source
            sources.append(code_str)
            _, out = self._kernel_eval(code_str)
            outputs.append(out)

        return((sources, outputs))
