"""
pytest ipython plugin modification

Authors: D. Cortes, O. Laslett

"""

import pytest
import os
import sys
import re

try:
    from exceptions import Exception
except:
    pass

wrapped_stdin = sys.stdin
sys.stdin = sys.__stdin__

# Kernel for IPython notebooks
from IPython.kernel.manager import start_new_kernel

sys.stdin = wrapped_stdin
try:
    from Queue import Empty
except:
    from queue import Empty

# from IPython.nbformat.current import reads, NotebookNode
from IPython.nbformat import reads, NotebookNode


# Colours for outputs
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'


def get_message(iopub, timeout=None):
    return iopub.get_msg(timeout=timeout)


def execute_cell_input(kc, cell_input, allow_stdin=None):
    return kc.execute(cell_input, allow_stdin=allow_stdin)


# These options are in case we wanted to restart the nb every time
# it is executed a certain task
def restart(km):
    km.restart_kernel(now=True)


def stop(kc, km):
    kc.stop_channels()
    km.shutdown_kernel(now=True)
    del km


# Read through the specified notebooks and load the data
# (which is in json format)
def collect(fspath, iopub):
    print fspath
    with open(fspath) as f:
        # self.nb = reads(f.read(), 'json')
        nb = reads(f.read(), 4)

        # Start the cell count
        cell_num = 0

        # Worksheets are NOT used anymore::
        # Currently there is only 1 worksheet (it seems in newer versions
        # of IPython, they are going to get rid of this option)
        # For every worksheet, read every cell associated to it

        for cell in nb.cells:
            # Skip the cells that have text, headings or related stuff
            # Only test code cells
            if cell.cell_type == 'code':

                # If the code is a notebook magic cell, do not run
                # i.e. cell code starts with '%%'
                # Also ignore the cells that start with the
                # comment string PYTEST_VALIDATE_IGNORE_OUTPUT
                # NOTE: This actually skips execution, which probably isn't what we want!
                #       It is typically helpful to execute the cell (to make sure that at
                #       least the code doesn't fail) but then discard the result.
                if not (cell.source.startswith('%%') or
                        cell.source.startswith(r'# PYTEST_VALIDATE_IGNORE_OUTPUT') or
                        cell.source.startswith(r'#PYTEST_VALIDATE_IGNORE_OUTPUT')):

                    runtest(cell, iopub)

                else:
                    # Skipped cells will not be counted
                    continue

            # Update 'code' cell count
            cell_num += 1


def teardown(kernel):
    kernel.stop()


def runtest(cell, iopub):
    """
    Run all the cell tests in one kernel without restarting.
    It is very common for ipython notebooks to run through assuming a
    single kernel.
    """
    # Execute the code from the current cell and get the msg_id
    # of the shell process.
    msg_id = execute_cell_input(kc, cell.source, allow_stdin=False)

    # Time for the reply of the cell execution
    timeout = 2000

    # This list stores the output information for the entire cell
    outs = []

    # Wait for the execution reply (we can see this in the msg_type)
    # This execution produces a dictionary where a status string can be
    # obtained: 'ok' OR 'error' OR 'abort'
    # We can also get how many cells have been executed
    # until here, with the 'execution_count' entry
    # self.parent.kernel.kc.get_shell_msg(timeout=timeout)

    while True:
        """
        The messages from the cell contain information such
        as input code, outputs generated
        and other messages. We iterate through each message
        until we reach the end of the cell.
        """
        try:
            # Get one message at a time, per code block inside the cell
            msg = get_message(iopub, timeout=1.)

        except Empty:
            # This is not working: ! The code will not be checked
            # if the time is out (when the cell stops to be executed?)
            # raise NbCellError("Timeout of %d seconds exceeded"
            #                      " executing cell: %s" (timeout,
            #                                             self.cell.input))
            # Just break the loop when the output is empty
            break

        """
        Now that we have the output from a piece of code
        inside the cell,
        we want to compare the outputs of the messages
        to a reference output (the ones that are present before
        the notebook was executed)
        """

        # print msg

        # Firstly, get the msg type from the cell to know if
        # the output comes from a code
        # It seems that the type 'stream' is irrelevant
        msg_type = msg['msg_type']
        reply = msg['content']

        # REF:
        # execute_input: To let all frontends know what code is
        # being executed at any given time, these messages contain a
        # re-broadcast of the code portion of an execute_request,
        # along with the execution_count.
        if msg_type == 'status':
            if reply['execution_state'] == 'idle':
                break
            else:
                continue
        elif msg_type == 'execute_input':
            continue
        elif msg_type.startswith('comm'):
            continue
        elif msg_type == 'execute_reply':
            # print msg
            continue
        # If there is no more output, continue with the executions
        # (it will break if it is empty, with the previous statements)
        #
        # REF:
        # This message type is used to clear the output that is
        # visible on the frontend
        # elif msg_type == 'clear_output':
        #     outs = []
        #     continue

        # I added the msg_type 'idle' condition (when the cell stops)
        # so we get a complete cell output
        # REF:
        # When the kernel starts to execute code, it will enter the 'busy'
        # state and when it finishes, it will enter the 'idle' state.
        # The kernel will publish state 'starting' exactly
        # once at process startup.
        # elif (msg_type == 'clear_output'
        #       and msg_type['execution_state'] == 'idle'):
        #     outs = []
        #     continue

        # WE COULD ADD HERE a condition for the 'error' message type
        # Making the test to fail

        """
        Now we get the reply from the piece of code executed
        and analyse the outputs
        """
        reply = msg['content']
        out = NotebookNode(output_type=msg_type)

        # Now check what type of output it is
        if msg_type == 'stream':
            out.stream = reply['name']
            out.text = reply['text']

        elif msg_type in ('display_data', 'execute_result'):
            # REF:
            # data and metadata are identical to a display_data message.
            # the object being displayed is that passed to the display
            #  hook, i.e. the *result* of the execution.
            out['metadata'] = reply['metadata']
            for mime, data in reply['data'].iteritems():
                attr = mime.split('/')[-1].lower()
                attr = attr.replace('+xml', '').replace('plain', 'text')
                setattr(out, attr, data)
            if msg_type == 'execute_result':
                out.prompt_number = reply['execution_count']
        else:
            print("unhandled iopub msg:", msg_type)

        outs.append(out)

        print '--------------------------- CELL --------------------------'
        print outs


km, kc = start_new_kernel(extra_arguments=['--matplotlib=inline'],
                          stderr=open(os.devnull, 'w'))
# We need iopub to read every line in the cells
iopub = kc.iopub_channel

collect(sys.argv[-1], iopub)
