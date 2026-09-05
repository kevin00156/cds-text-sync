# -*- coding: utf-8 -*-
"""Tests for cds.ide.silent — running a script with nobody at the keyboard.

The scripts under test are stand-ins written into tmp_path, shaped like the
real Project_*.py: they reach for `system` from their own globals, and they
reach for ask_yes_no through sys.modules["codesys_ui"] at call time. Running
the real ones needs a real IDE, which is the hand test in the plan.
"""
import codecs
import io
import os
import re
import sys
import types

import pytest

from cds.ide import silent


class FakeSystem(object):
    def __init__(self):
        self.ui = "the real ui, which must survive"
        self.abortable = False

    def delay(self, ms):
        pass


@pytest.fixture
def ide():
    return {"system": FakeSystem(), "projects": object()}


@pytest.fixture
def fake_codesys_ui():
    """Stand in for the module the scripts reload on every run."""
    module = types.ModuleType("codesys_ui")

    def ask_yes_no(title, message):
        raise AssertionError("a real message box was opened")

    def ask_yes_no_cancel(title, message):
        raise AssertionError("a real message box was opened")

    def show_compare_dialog(*args):
        raise AssertionError("a real compare window was opened")

    module.ask_yes_no = ask_yes_no
    module.ask_yes_no_cancel = ask_yes_no_cancel
    module.show_compare_dialog = show_compare_dialog
    sys.modules["codesys_ui"] = module
    yield module
    del sys.modules["codesys_ui"]


def write_script(tmp_path, body, name="Project_fake.py"):
    path = tmp_path / name
    path.write_text(
        u"# -*- coding: utf-8 -*-\n"
        u"import sys\n"
        u"RAN_AS_MAIN = False\n"
        u"def main():\n" + body + u"\n"
        u"if __name__ == '__main__':\n"
        u"    RAN_AS_MAIN = True\n"
        u"    main()\n",
        encoding="utf-8")
    return str(path)


# --- the namespace ---------------------------------------------------------

def test_the_script_does_not_run_itself(tmp_path, ide):
    path = write_script(tmp_path, u"    system.ui.info('ran')")
    outcome = silent.run(ide, path, "main", {})
    assert len(outcome.messages) == 1  # once, from our call, not twice


def test_the_script_sees_the_stand_in_ui(tmp_path, ide):
    path = write_script(tmp_path, u"    system.ui.info(u'hello')")
    outcome = silent.run(ide, path, "main", {})
    assert outcome.messages == [{"level": "info", "text": u"hello"}]
    assert outcome.ok()


def test_everything_but_ui_still_reaches_the_real_system(tmp_path, ide):
    path = write_script(tmp_path, u"    system.delay(1)\n"
                                  u"    system.ui.info(str(system.abortable))")
    assert silent.run(ide, path, "main", {}).messages[0]["text"] == "False"


def test_the_real_system_is_put_back_afterwards(tmp_path, ide):
    path = write_script(tmp_path, u"    system.ui.info('x')")
    silent.run(ide, path, "main", {})
    assert ide["system"].ui == "the real ui, which must survive"


def test_a_utf8_script_with_a_coding_line_compiles(tmp_path, ide):
    # IronPython 2.7 rejects a coding declaration in unicode source, so the
    # runner compiles from bytes. Keep a non-ASCII literal here to prove it.
    path = write_script(tmp_path, u"    system.ui.info(u'\u532f\u5165\u5b8c\u6210')")
    assert silent.run(ide, path, "main", {}).messages[0]["text"] == u"匯入完成"


# --- what the script printed -----------------------------------------------

def test_stdout_is_captured_and_still_printed(tmp_path, ide, capsys):
    path = write_script(tmp_path, u"    print('line one')\n    print('line two')")
    outcome = silent.run(ide, path, "main", {})
    assert outcome.stdout_tail == "line one\nline two"
    assert "line one" in capsys.readouterr().out


def test_only_the_tail_is_kept(tmp_path, ide):
    path = write_script(tmp_path,
                        u"    for i in range(500): print('line %d' % i)")
    tail = silent.run(ide, path, "main", {}).stdout_tail.splitlines()
    assert len(tail) == silent.STDOUT_TAIL_LINES
    assert tail[-1] == "line 499"


def test_stdout_is_restored_even_when_the_script_blows_up(tmp_path, ide):
    original = sys.stdout
    path = write_script(tmp_path, u"    raise ValueError('boom')")
    outcome = silent.run(ide, path, "main", {})
    assert sys.stdout is original
    assert "boom" in outcome.error and not outcome.ok()


# --- answering the dialogs -------------------------------------------------

def yes_no_script(tmp_path, title):
    return write_script(tmp_path,
                        u"    from codesys_ui import ask_yes_no\n"
                        u"    system.ui.info('answered ' + "
                        u"str(ask_yes_no(%r, 'because')))" % str(title))


def test_a_yes_no_dialog_is_answered_from_the_arguments(tmp_path, ide,
                                                        fake_codesys_ui):
    path = yes_no_script(tmp_path, "Delete Orphaned Files?")
    outcome = silent.run(ide, path, "main", {"delete_orphans": True})
    assert outcome.messages[0]["text"] == "answered True"


def test_a_yes_no_dialog_with_no_argument_takes_its_default(tmp_path, ide,
                                                            fake_codesys_ui):
    path = yes_no_script(tmp_path, "Delete Orphaned Files?")
    outcome = silent.run(ide, path, "main", {})
    assert outcome.messages[0]["text"] == "answered False"


def test_confirm_import_has_no_default_and_asks(tmp_path, ide, fake_codesys_ui):
    # Importing without being told to is exactly what must never happen.
    path = yes_no_script(tmp_path, "Confirm Import")
    outcome = silent.run(ide, path, "main", {})
    assert outcome.needs.arg == "yes"
    assert not outcome.ok()


def test_an_unknown_dialog_is_refused_rather_than_guessed(tmp_path, ide,
                                                          fake_codesys_ui):
    path = yes_no_script(tmp_path, "Some New Question")
    outcome = silent.run(ide, path, "main", {"yes": True})
    assert outcome.needs is not None
    assert "Some New Question" in outcome.needs.question


def test_the_computer_mismatch_cancels_unless_forced(tmp_path, ide,
                                                     fake_codesys_ui):
    body = (u"    from codesys_ui import ask_yes_no_cancel\n"
            u"    system.ui.info(ask_yes_no_cancel("
            u"'Computer Mismatch Detected', 'm'))")
    path = write_script(tmp_path, body)
    assert silent.run(ide, path, "main", {}).messages[0]["text"] == "cancel"
    assert silent.run(ide, path, "main", {"force": True}
                      ).messages[0]["text"] == "no"


def test_the_compare_window_is_replaced_by_a_summary(tmp_path, ide,
                                                     fake_codesys_ui):
    body = (u"    from codesys_ui import show_compare_dialog\n"
            u"    action, selected = show_compare_dialog("
            u"[1, 2], [3], [], 7, [])\n"
            u"    system.ui.info('action=%s' % (action,))")
    path = write_script(tmp_path, body)
    outcome = silent.run(ide, path, "main", {})
    assert "modified 2" in outcome.messages[0]["text"]
    assert outcome.messages[1]["text"] == "action=None"


def test_codesys_ui_is_put_back_afterwards(tmp_path, ide, fake_codesys_ui):
    path = yes_no_script(tmp_path, "Delete Orphaned Files?")
    silent.run(ide, path, "main", {})
    with pytest.raises(AssertionError):
        sys.modules["codesys_ui"].ask_yes_no("x", "y")


# --- the shared .pyw modules reach __main__ --------------------------------

def test_a_module_that_looks_at_main_gets_the_stand_in(tmp_path, ide):
    # codesys_utils:517 finds `system` through __main__, not through the
    # calling script's globals, so __main__ has to be swapped too.
    body = (u"    import __main__\n"
            u"    __main__.system.ui.info('through __main__')")
    path = write_script(tmp_path, body)
    assert silent.run(ide, path, "main", {}).messages[0]["text"] == \
        "through __main__"


def test_main_is_put_back_afterwards(tmp_path, ide):
    before = getattr(sys.modules["__main__"], "system", "absent")
    path = write_script(tmp_path, u"    system.ui.info('x')")
    silent.run(ide, path, "main", {})
    assert getattr(sys.modules["__main__"], "system", "absent") == before


# --- choosing an application -----------------------------------------------

def choose_script(tmp_path):
    return write_script(tmp_path,
                        u"    try:\n"
                        u"        i = system.ui.choose('pick', ['App', 'Other'])\n"
                        u"        system.ui.info('chose %d' % i)\n"
                        u"    except Exception as e:\n"
                        u"        system.ui.info('swallowed')")


def test_choose_picks_the_named_application(tmp_path, ide):
    outcome = silent.run(ide, choose_script(tmp_path), "main", {"app": "Other"})
    assert outcome.messages[0]["text"] == "chose 1"


def test_choose_without_a_name_is_not_swallowed_by_except_exception(tmp_path, ide):
    # Project_Build.py wraps the chooser in `except Exception`, which would
    # otherwise turn "you did not say which app" into a silent wrong build.
    outcome = silent.run(ide, choose_script(tmp_path), "main", {})
    assert outcome.needs is not None and outcome.needs.arg == "app"
    assert [m["text"] for m in outcome.messages] == []


def test_choose_rejects_a_name_that_is_not_there(tmp_path, ide):
    outcome = silent.run(ide, choose_script(tmp_path), "main", {"app": "Ghost"})
    assert "Ghost" in outcome.needs.question


def test_any_other_dialog_says_it_needs_a_person(tmp_path, ide):
    path = write_script(tmp_path, u"    system.ui.query_string('name?', '')")
    outcome = silent.run(ide, path, "main", {})
    assert "query_string" in outcome.needs.question


# --- the verdict -----------------------------------------------------------

def test_a_warning_counts_as_failure(tmp_path, ide):
    # The scripts abort by warning and returning; there is no return value.
    path = write_script(tmp_path, u"    system.ui.warning('sync folder not set')")
    outcome = silent.run(ide, path, "main", {})
    assert not outcome.ok()
    assert outcome.error_text() == "sync folder not set"


def test_an_error_counts_as_failure(tmp_path, ide):
    path = write_script(tmp_path, u"    system.ui.error('no project open')")
    assert not silent.run(ide, path, "main", {}).ok()


def test_plain_information_is_success(tmp_path, ide):
    path = write_script(tmp_path, u"    system.ui.info('Export complete!')")
    outcome = silent.run(ide, path, "main", {})
    assert outcome.ok() and outcome.error_text() is None


# --- a script that gives up quietly ----------------------------------------

def test_a_script_that_reports_nothing_is_a_failure(tmp_path, ide):
    # Project_import.py used to have two give-up paths that only print(), so
    # a cancelled import came back ok=True and the caller went on to build
    # code that was never imported.
    path = write_script(tmp_path, u"    print('Import cancelled.')")
    outcome = silent.run(ide, path, "main", {})
    assert not outcome.ok()
    assert "without reporting anything" in outcome.error_text()
    assert outcome.stdout_tail == "Import cancelled."


def test_one_info_is_enough_to_count_as_finished(tmp_path, ide):
    path = write_script(tmp_path, u"    system.ui.info('Export complete!')")
    assert silent.run(ide, path, "main", {}).ok()


# --- the dialog titles are copies of literals in four other files ----------

DRIVEN_FILES = (
    # What the four commands actually execute. Project_directory.py is left
    # out on purpose: its dialog is only reachable after "Computer Mismatch"
    # is answered yes, and silent mode never answers yes.
    "Project_export.py", "Project_import.py", "Project_compare.py",
    "Project_Build.py", "codesys_utils.pyw", "codesys_managers.pyw",
    "codesys_compare_engine.pyw", "codesys_online.pyw",
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def titles_asked_for(function):
    """Every literal title passed to `function` anywhere the commands reach."""
    pattern = re.compile(function + r'\(\s*"([^"]+)"')
    found = set()
    for name in DRIVEN_FILES:
        with io.open(os.path.join(REPO_ROOT, name), encoding="utf-8") as handle:
            found.update(pattern.findall(handle.read()))
    return found


def test_every_yes_no_dialog_has_an_answer():
    # Nothing else keeps these two in step. Rename a title in one of those
    # files and export or import starts failing with "unexpected dialog",
    # while every test here stays green because they use stand-in scripts.
    assert titles_asked_for("ask_yes_no") <= set(silent.YES_NO)


def test_every_yes_no_cancel_dialog_has_an_answer():
    assert titles_asked_for("ask_yes_no_cancel") <= set(silent.YES_NO_CANCEL)


def test_the_answer_tables_are_not_carrying_dead_titles():
    assert set(silent.YES_NO) == titles_asked_for("ask_yes_no")
    assert set(silent.YES_NO_CANCEL) == titles_asked_for("ask_yes_no_cancel")


def test_an_unknown_yes_no_cancel_dialog_is_refused(tmp_path, ide,
                                                    fake_codesys_ui):
    body = (u"    from codesys_ui import ask_yes_no_cancel\n"
            u"    ask_yes_no_cancel('Brand New Question', 'm')")
    outcome = silent.run(ide, write_script(tmp_path, body), "main", {})
    assert "Brand New Question" in outcome.needs.question


# --- the exec path ---------------------------------------------------------

def test_a_script_saved_with_a_bom_still_compiles(tmp_path, ide):
    # Python 2's compile() chokes on a BOM, and Windows editors add them.
    path = tmp_path / "Project_bom.py"
    body = (u"# -*- coding: utf-8 -*-\n"
            u"def main():\n"
            u"    system.ui.info('past the bom')\n")
    path.write_bytes(codecs.BOM_UTF8 + body.encode("utf-8"))
    outcome = silent.run(ide, str(path), "main", {})
    assert outcome.messages[0]["text"] == "past the bom"


def test_nothing_is_running_before_or_after_a_run(tmp_path, ide):
    assert silent.running() is False
    path = write_script(tmp_path, u"    system.ui.info(str(1))")
    silent.run(ide, path, "main", {})
    assert silent.running() is False


def test_the_running_flag_is_up_inside_the_script(tmp_path, ide):
    path = write_script(tmp_path,
                        u"    import cds.ide.silent as s\n"
                        u"    system.ui.info(str(s.running()))")
    assert silent.run(ide, path, "main", {}).messages[0]["text"] == "True"
