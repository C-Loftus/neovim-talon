from talon import Module, actions, settings, ui, app

from .rpc import NeoVimRPC
from ..error import VimError

import time

# TODO: move this file to core/modes/modes.py instead as is not rpc stuff but just relies on it?


# XXX - this should be updated to use feedkeys when RPC is available
# XXX - this should be made a singleton they gets registered when the window
# is focused
# XXX - this has a lot of code specific to VimDirectInput rather than VimRPC
# should be broken up were appropriate.
class VimMode:
    """Manage mode transitions with or without RPC"""

    # mode ids represent generic statusline mode() values. see :help mode()
    # TODO: need to add "normal_terminal" too?
    NORMAL = "normal"
    VISUAL = "visual"
    VISUAL_LINE = "visual_line"
    VISUAL_BLOCK = "visual_block"
    INSERT = "insert"
    TERMINAL = "terminal"
    COMMAND_LINE = "command_line"
    REPLACE = "replace"
    VISUAL_REPLACE = "visual_replace"

    # This is replicated from :help mode()
    vim_modes_new = {"NORMAL": {"mode": "n", "desc": "Normal"}}

    # XXX - incomplete see :help mode
    vim_modes = {
        "n": "Normal",
        "no": "N Operator Pending",
        "v": "Visual",
        "V": "V Line",
        "^V": "V-Block",
        "s": "Select",
        "S": "S·Line",
        "i": "Insert",
        "R": "Replace",
        "Rv": "V·Replace",
        "c": "Command",
        "cv": "Vim Ex",
        "ce": "Ex",
        "r": "Prompt",
        "rm": "More",
        "r?": "Confirm",
        "!": "Shell",
        "t": "Terminal",
    }

    vim_normal_mode_indicators = [
        "n",
        "no",
        "nov",
        "noV",
        "no^V",
        "niI",
        "niR",
        "niV",
    ]

    def __init__(self):
        # list of all vim instances talon is aware of
        self.vim_instances = []
        self.current_rpc = None
        self.nvrpc = NeoVimRPC()
        self.canceled_timeout = 0.20
        self.wait_mode_timeout = 0.25

    def __del__(self):
        if self.nvrpc.init_ok is True:
            self.nvrpc.nvim.close()

    def is_normal_mode(self):
        return self.mode() in self.vim_normal_mode_indicators

    # XXX - move these to arrays like vim_normal_mode_indicators
    def is_visual_mode(self):
        return self.mode() in ["v", "V", "^V"]

    def is_insert_mode(self):
        return self.mode() in ["i", "ic", "ix"]

    def is_terminal_mode(self):
        return self.mode() == "t"

    def is_command_mode(self):
        return self.mode() == "c"

    def is_replace_mode(self):
        return self.mode() in ["R", "Rv", "Rx", "Rc"]

    # XXX - this can maybe get called by the parent class, since will only have
    # when the parent class is VimRPC
    def mode(self):
        if self.nvrpc.init_ok is True:
            mode = self.nvrpc.get_active_mode()["mode"]
        else:
            title = ui.active_window().title
            mode = None
            if "MODE:" in title:
                mode = title.split("MODE:")[1].split(" ")[0]
                if mode not in self.vim_modes.keys():
                    return None

        return mode

    def current_mode_id(self):
        if self.is_normal_mode():
            return self.NORMAL
        elif self.is_visual_mode():
            return self.VISUAL
        elif self.is_insert_mode():
            return self.INSERT
        elif self.is_terminal_mode():
            return self.TERMINAL
        elif self.is_command_mode():
            return self.COMMAND_LINE

    def mode_to_tag(mode):
        if mode == VimMode.NORMAL:
            return "user.vim_mode_normal"
        elif mode == VimMode.VISUAL:
            return "user.vim_mode_visual"
        elif mode == VimMode.INSERT:
            return "user.vim_mode_insert"
        elif mode == VimMode.TERMINAL:
            return "user.vim_mode_terminal"
        elif mode == VimMode.COMMAND_LINE:
            return "user.vim_mode_command"

    def insert_text(self, text):
        # actions.user.paste(text) # TODO: this is community
        # actions.user.paste_text(text)  # TODO: this is andreas-talon
        # TODO: below can be deleted?
        if app.platform == "linux":
            actions.user.paste(text)
        else:
            actions.insert(text)

    def insert_command_mode_command(self, cmd):
        """prepare the command to be pasted into command mode"""
        # strip the new line to prevent it breaking on mac
        scmd = cmd.rstrip("\n")
        if scmd[0] == ":":
            self.insert_text(scmd[1:])
        else:
            self.insert_text(scmd)
        if cmd[-1] == "\n":
            actions.key("enter")

    def set_normal_mode(self, auto=True):
        return self.adjust_mode(self.NORMAL, auto=auto)

    def set_normal_mode_exterm(self):
        return self.adjust_mode(self.NORMAL, escape_terminal=True)

    # XXX - revisit auto, maybe have separate method version or something
    def set_normal_mode_np(self, auto=True):
        return self.adjust_mode(self.NORMAL, no_preserve=True, auto=auto)

    def set_visual_mode(self):
        return self.adjust_mode(self.VISUAL)

    def set_visual_mode_np(self):
        return self.adjust_mode(self.VISUAL, no_preserve=True)

    def set_visual_line_mode(self):
        return self.adjust_mode(self.VISUAL_LINE)

    def set_visual_block_mode(self):
        return self.adjust_mode(self.VISUAL_BLOCK)

    def set_insert_mode(self):
        return self.adjust_mode(self.INSERT)

    def set_terminal_mode(self):
        return self.adjust_mode(self.TERMINAL)

    def set_command_mode(self):
        return self.adjust_mode(self.COMMAND_LINE)

    def set_command_mode_exterm(self):
        return self.adjust_mode(self.COMMAND_LINE, escape_terminal=True)

    def set_replace_mode(self):
        return self.adjust_mode(self.REPLACE)

    def set_visual_replace_mode(self):
        return self.adjust_mode(self.VISUAL_REPLACE)

    def set_any_motion_mode(self):
        return self.adjust_mode([self.NORMAL, self.VISUAL])

    # XXX - this should accept additional modes, like visual block
    def set_any_motion_mode_exterm(self):
        return self.adjust_mode([self.NORMAL, self.VISUAL], escape_terminal=True)

    def set_any_motion_mode_np(self):
        return self.adjust_mode(self.NORMAL, no_preserve=True)

    def adjust_mode(
        self, valid_mode_ids, no_preserve=False, escape_terminal=False, auto=True
    ):
        cur = self.current_mode_id()
        if type(valid_mode_ids) != list:
            valid_mode_ids = [valid_mode_ids]
        if cur not in valid_mode_ids:
            # Just favor the first mode match
            self.set_mode(
                valid_mode_ids[0],
                no_preserve=no_preserve,
                escape_terminal=escape_terminal,
            )
            # Trigger / untrigger mode-related talon grammars
            self.set_mode_tag(valid_mode_ids[0])
            return VimError.SUCCESS
        else:
            return VimError.SUCCESS_MODE_ALREADY_SET

    # Often I will say `delete line` and it will trigger `@delete` and `@nine`.
    # This then keys 9. I then say `undo` to fix the bad delete, which does 9
    # undos. Chaos ensues... this seeks to fix that
    def cancel_queued_commands(self):
        if self.is_normal_mode():
            actions.key("escape")
            time.sleep(self.canceled_timeout)

    def wait_mode_change(self, wanted):
        check_count = 0
        max_check_count = 20
        if self.nvrpc.init_ok:
            active_mode = self.nvrpc.get_active_mode()["mode"]
            while wanted != active_mode:
                # XXX - There's probably a cleaner way to do this, but there's
                # a lot of normal modes which we don't seem to match on, but
                # technically should
                if wanted == "n" and active_mode in self.vim_normal_mode_indicators:
                    return True

                # XXX - for wait value should be configurable
                time.sleep(0.020)
                # try to force redraw to prevent weird infinite loops
                self.nvrpc.nvim.command("redraw")
                check_count += 1
                if check_count > max_check_count:
                    # prevent occasional infinite loops stalling talon
                    return False
                active_mode = self.nvrpc.get_active_mode()["mode"]

            return True
        else:
            time.sleep(self.wait_mode_timeout)
            return True

    @classmethod
    # We don't want unnecessarily only call this from set_mode() is the user
    # might change the mode of vim manually or speaking keys, but we still want
    # the context specific grammars to match.
    # TODO: figure out if this makes sense in addition to win.title matching I
    # already do. I think it does make sense for cases of overriding certain
    # default actions like home/end
    def set_mode_tag(self, mode):
        global ctx

    # NOTE: querying certain modes is broken (^V mode undetected)
    # Setting mode with RPC is impossible, which makes sense because it would
    # break things like macro recording/replaying. So we use keyboard
    # combinations
    def set_mode(self, wanted_mode, no_preserve=False, escape_terminal=False):
        current_mode = self.mode()
        if current_mode == wanted_mode or (
            self.is_terminal_mode() and wanted_mode == self.INSERT
        ):
            return

        # enter normal mode where necessary
        # XXX - need to handle normal mode in Command Line window, we need to
        # be able to escape from it
        # XXX - also have a lot of special case modes (see :help mode) that we
        # probably want to be able to break out of, instead of just doing more
        # fuzzy matching of the mode (ex: `no`, `rm`, `!`, etc)
        if self.is_terminal_mode():
            if escape_terminal is True:
                # break out of terminal mode
                actions.key("ctrl-\\")
                actions.key("ctrl-n")

                # XXX - Not sure why I have to sleep after this, but otherwise
                # sit sometimes blocks for way longer then it should
                time.sleep(0.05)

                self.wait_mode_change("n")
            else:
                # Imagine you have a vim terminal and inside you're running a
                # terminal that is using vim mode rather than emacs mode. This
                # means you will want to be able to use some amount of vim
                # commands to edit the shells command line itself without
                # actually being inside the encapsulating vim instance.
                # The use of escape here tries to compensate for those
                # scenerios, where you won't break into the encapsulating vim
                # instance. Needs to be tested.
                actions.key("escape")
                # NOTE: do not wait on mode change here, as we
                # cannot detect it
        elif self.is_insert_mode():
            # XXX - this might need to be a or for no_preserve and
            # settings.get?
            if wanted_mode == self.NORMAL and no_preserve is False:
                # When you preserve mode and switch into into insert mode it will often
                # move your cursor, which can mess up the commands you're trying to run from
                # insert. This avoids that
                actions.key("ctrl-\\")

                actions.key("ctrl-o")
                # XXX - Same oddity as terminal escape above
                time.sleep(0.05)
                self.wait_mode_change("niI")
            else:
                # Presses right because entering normal mode via escape puts
                # the cursor back one position, otherwise misaligns on words.
                # Exception is `2 delete big-back` from INSERT mode.
                actions.key("right")
                actions.key("escape")
                time.sleep(0.05)
                self.wait_mode_change("n")
        elif self.is_visual_mode() or self.is_command_mode() or self.is_replace_mode():
            actions.key("escape")
            time.sleep(0.05)
            self.wait_mode_change("n")
        elif self.is_normal_mode() and wanted_mode == self.COMMAND_LINE:
            # We explicitly escape even if normal mode, to cancel any queued
            # commands that might affect our command. For instance, accidental
            # number queueing followed by :w, etc
            actions.key("escape")
            time.sleep(0.05)
            time.sleep(self.canceled_timeout)
            self.wait_mode_change("n")

        # switch to explicit mode if necessary. we will be normal mode here
        if wanted_mode == self.INSERT or wanted_mode == self.TERMINAL:
            actions.key("i")
        # or just let the original 'mode' command run from this point
        elif wanted_mode == self.VISUAL:
            # first we cancel queued normal commands that might mess with 'v'
            # ex: normal mode press 5, then press v to switch to visual
            actions.key("escape")
            actions.key("v")
        elif wanted_mode == self.VISUAL_LINE:
            # first we cancel queued normal commands that might mess with 'v'
            # ex: normal mode press 5, then press v to switch to visual
            actions.key("escape")
            actions.key("V")
        elif wanted_mode == self.VISUAL_BLOCK:
            # first we cancel queued normal commands that might mess with 'v'
            # ex: normal mode press 5, then press v to switch to visual
            actions.key("escape")
            actions.key("ctrl-v")
        elif wanted_mode == self.COMMAND_LINE:
            actions.key(":")
            self.wait_mode_change("c")
        elif wanted_mode == self.REPLACE:
            actions.key("R")
        elif wanted_mode == self.VISUAL_REPLACE:
            actions.key("g R")
