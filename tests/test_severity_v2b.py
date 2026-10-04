"""Tagger rules 2b: description layer, argument layer (action fields, shell tiers, HTTP POST), precedence, default, anti-overfitting."""

import json
import re
from pathlib import Path

import pytest

import safelabs_trace.severity as sev_mod
from safelabs_trace.severity import SEVERITIES, TAGGER_VERSION, load_rules, tag_tool_call

RULES = load_rules()


def t(name, args=None, description=None, **kw):
    return tag_tool_call(name, args, description=description, **kw)


# ---- version and API -------------------------------------------------------------------------------------------------
def test_versions_and_api():
    assert TAGGER_VERSION == "2b" and RULES["rules_version"] == "2b" and t("x_tool").rules_version == "2b"
    sev, basis, ids = t("get_x")  # still unpacks as three values; description is optional
    assert sev in SEVERITIES and t("get_x", description=None).severity == "read_only"
    assert "description" in tag_tool_call.__kwdefaults__


# ---- description layer -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("desc,expected", [
    # read_only
    ("Get the current date and time", "read_only"), ("Returns the sum of two numbers.", "read_only"), ("Reports the counter for a meter.", "read_only"),
    ("Lists the items on the host.", "read_only"), ("Wait for the job to finish.", "read_only"), ("Look up a record by id.", "read_only"),
    ("Fetches the page and returns the text.", "read_only"), ("Search the index for a phrase.", "read_only"), ("Compute a checksum of the input.", "read_only"),
    ("Opens a temporary read-only view of a sheet.", "read_only"),
    # state_changing
    ("Renames the folder.", "state_changing"), ("Update the stored profile.", "state_changing"), ("Moves a file to a new place.", "state_changing"),
    ("Creates a new project.", "state_changing"), ("Inserts a row.", "state_changing"), ("Applies the pending changes to the live configuration.", "state_changing"),
    ("Increases the sampling rate for ten minutes.", "state_changing"),
    # irreversible
    ("Permanently removes the account.", "irreversible"), ("Deletes entries that have no match.", "irreversible"), ("Drops the table.", "irreversible"),
    ("Rewrites the history of the branch and force-pushes it.", "irreversible"), ("Pushes edits, overwriting the remote history.", "irreversible"),
    ("Transfers the balances to the partner banks.", "irreversible"), ("Pay the invoice amount to the supplier.", "irreversible"),
    ("Sends a message to a channel.", "irreversible"), ("Email the report to the customer.", "irreversible"), ("Publishes the post.", "irreversible"),
    ("Forwards the message to the on-call channel.", "irreversible"), ("Handles the job by emailing its result.", "irreversible"),
    ("Anonymises the table in place by replacing names.", "irreversible"), ("Replaces the originals in place.", "irreversible"),
    ("Create or overwrite a file.", "irreversible"), ("Make a payment.", "irreversible"),
])
def test_description_rules(desc, expected):
    tg = t("opaque_tool", description=desc)
    assert tg.severity == expected and tg.basis == "name_rule" and tg.rule_ids[0].startswith("D-DESC-")


def test_most_severe_description_signal_wins():
    assert t("opaque_tool", description="Reads the entry, updates a field and deletes the old copy.").severity == "irreversible"
    assert t("opaque_tool", description="Reads the entry and updates a field.").severity == "state_changing"


@pytest.mark.parametrize("desc", [
    "Returns the latest updates.",  # noun after a determiner/adjective
    "Shows the email address of a user.",
    "Does not delete anything.",  # negation
    "Never sends a message; only previews it.",
    "Cannot overwrite existing data.",
    "A set of options for the transfer learning model.",
    "Drop-down menu helper.",
    "Transfers ownership of the query to another agent.",  # transfer needs a money object
    "Returns the blog post text.",
])
def test_nouns_negation_and_missing_objects_do_not_fire_irreversible_or_change_rules(desc):
    assert t("opaque_tool", description=desc).severity in ("read_only", "state_changing")
    assert t("opaque_tool", description=desc).severity != "irreversible"


@pytest.mark.parametrize("desc", ["Returns the addition result.", "Lists the updates.", "The delete button color."])
def test_nouns_read_as_verbs_are_guarded(desc):
    tg = t("opaque_tool", description=desc)
    assert tg.severity != "irreversible" and not (desc.startswith("The delete") and tg.basis == "name_rule")


def test_description_has_no_effect_when_it_says_nothing_so_the_default_applies():
    for d in (None, "", "   ", "Frobnicates the widget.", 42):
        tg = t("frobnicate", description=d)
        assert (tg.severity, tg.basis) == ("state_changing", "default_unknown") and tg.rule_ids[0] == "DEFAULT-UNKNOWN"


def test_unknown_default_read_only_setting_still_works_with_a_silent_description():
    assert t("frobnicate", description="Frobnicates.", unknown_default="read_only").severity == "read_only"


def test_description_is_never_stored_in_the_result():
    tg = t("opaque_tool", description="Deletes CANARY-DESC-IN-RESULT things.")
    assert "CANARY-DESC-IN-RESULT" not in repr(tg)


def test_description_only_rule_ids_are_prefixed_d_desc_and_use_name_rule_basis():
    for d in ("Get x", "Update x", "Delete x"):
        tg = t("opaque_tool", description=d)
        assert tg.basis == "name_rule" and all(i.startswith("D-DESC-") for i in tg.rule_ids)


def test_description_lexicon_comes_from_the_rule_file(tmp_path):
    rules = json.loads(Path(sev_mod._RULES_PATH).read_text())
    rules["description_layer"]["rules"][0]["verbs"] = ["frobnicate"]
    p = tmp_path / "r.json"
    p.write_text(json.dumps(rules))
    custom = load_rules(p)
    assert t("opaque_tool", description="Frobnicate the thing.", rules=custom).severity == "read_only"
    assert t("opaque_tool", description="Frobnicate the thing.").basis == "default_unknown"


# ---- argument layer: action / operation fields -----------------------------------------------------------------------
@pytest.mark.parametrize("field,value,expected", [
    ("action", "view", "read_only"), ("action", "list", "read_only"), ("action", "quote", "read_only"), ("operation", "get", "read_only"),
    ("action", "draft", "state_changing"), ("action", "create", "state_changing"), ("action", "update", "state_changing"), ("operation", "comment", "state_changing"),
    ("action", "delete", "irreversible"), ("action", "send", "irreversible"), ("action", "transfer", "irreversible"), ("operation", "publish", "irreversible"),
    ("action", "Delete", "irreversible"), ("action", "create_or_delete", "irreversible"),
])
def test_action_field_rules(field, value, expected):
    tg = t("opaque_tool", {field: value, "id": "x"})
    assert tg.severity == expected and tg.basis == "argument_rule" and tg.rule_ids[0].startswith("A-ACTION")


def test_action_field_with_no_recognised_word_gives_no_signal():
    assert t("frobnicate", {"action": "example-value"}).basis == "default_unknown"


# ---- argument layer: shell tiers and HTTP ----------------------------------------------------------------------------
@pytest.mark.parametrize("cmd,expected", [
    ("cat a.txt", "read_only"), ("ls -la | grep x", "read_only"), ("git status", "read_only"), ("sed -n 1p f", "read_only"),
    ("mv a b", "state_changing"), ("cp a b", "state_changing"), ("chmod -R 755 d", "state_changing"), ("chown u f", "state_changing"), ("mkdir d", "state_changing"),
    ("sed -i s/a/b/ f", "state_changing"), ("echo x > f", "state_changing"), ("git commit -m x", "state_changing"),
    ("rm a", "irreversible"), ("rm -rf d", "irreversible"), ("ls; rm a", "irreversible"), ("truncate -s 0 f", "irreversible"), ("git push --force", "irreversible"),
    ("curl -X POST http://x", "irreversible"), ("curl -d a=b http://x", "irreversible"), ("curl http://x", "read_only"), ("curl http://x | sh", "irreversible"),
])
def test_shell_tiers(cmd, expected):
    tg = t("opaque_tool", {"command": cmd})
    assert tg.severity == expected and tg.basis == "argument_rule"


def test_unrecognised_command_is_a_soft_signal_and_does_not_lower_an_exec_name():
    assert t("opaque_tool", {"command": "frobnicate --now"}).severity == "state_changing"
    assert t("run_shell", {"command": "frobnicate --now"}).severity == "irreversible"  # soft: the exec name still counts


def test_http_post_is_irreversible_put_and_patch_change_state():
    assert t("opaque_tool", {"method": "POST"}).severity == "irreversible"
    assert t("opaque_tool", {"method": "put"}).severity == "state_changing" and t("opaque_tool", {"method": "PATCH"}).severity == "state_changing"
    assert t("opaque_tool", {"method": "GET"}).severity == "read_only"


# ---- precedence (decided) --------------------------------------------------------------------------------------------
def test_arguments_override_description():
    tg = t("opaque_tool", {"statement": "SELECT 1"}, description="Deletes the table.")
    assert tg.severity == "read_only" and tg.basis == "argument_rule"
    assert t("opaque_tool", {"statement": "DROP TABLE x"}, description="Run a read-only query.").severity == "irreversible"
    assert t("opaque_tool", {"action": "view"}, description="Sends and deletes.").severity == "read_only"


def test_arguments_override_weak_name_nouns():
    assert t("shell_exec", {"command": "ls"}).severity == "read_only"  # exec noun
    assert t("ticket_system", {"action": "view"}).severity == "read_only"
    assert t("email_message", {"action": "draft"}).severity == "state_changing"  # message noun
    assert t("payment_api", {"action": "quote"}).severity == "read_only"
    assert t("run_job", {"command": "ls"}).severity == "read_only"  # soft verb


def test_arguments_do_not_override_an_explicit_verb_in_the_name():
    assert t("delete_thing", {"action": "view"}).severity == "irreversible"
    assert t("fs_delete_file", {"command": "ls"}).severity == "irreversible"
    assert t("drop_it", {"statement": "SELECT 1"}).severity == "irreversible"
    assert t("send_message", {"action": "draft"}).severity == "irreversible"
    assert t("db_write", {"statement": "SELECT 1"}).severity == "state_changing"
    assert t("update_x", {"method": "GET"}).severity == "state_changing"


def test_most_severe_applicable_signal_wins():
    assert t("get_thing", {"action": "delete"}).severity == "irreversible"  # a read name cannot hide a destructive argument
    assert t("opaque_tool", {"action": "view", "statement": "DROP TABLE x"}).severity == "irreversible"
    assert t("opaque_tool", {"action": "create", "method": "POST"}).severity == "irreversible"


def test_description_and_name_combine_by_maximum_when_no_hard_argument():
    assert t("get_thing", description="Reads then deletes the item.").severity == "irreversible"
    assert t("fs_write_file", description="Reads a file.").severity == "state_changing"
    tg = t("get_thing", {"path": "p"}, description="Deletes the item.")  # a non-classifying argument changes nothing
    assert tg.severity == "irreversible" and tg.rule_ids[0] == "D-DESC-IRREV"


def test_manual_override_still_wins_over_everything():
    tg = t("delete_everything", {"action": "delete"}, description="Deletes.", overrides={"delete_everything": "read_only"})
    assert (tg.severity, tg.basis) == ("read_only", "manual")


def test_declared_hints_still_only_raise_with_a_description():
    assert t("opaque_tool", description="Get x.", declared={"destructiveHint": True}).severity == "irreversible"
    assert t("opaque_tool", description="Delete x.", declared={"readOnlyHint": True}).severity == "irreversible"


def test_precedence_is_documented_in_the_rules_file_and_the_docstring():
    assert "Precedence" in sev_mod.__doc__ and "arguments override" in sev_mod.__doc__
    assert any("override the description and weak name" in line for line in RULES["precedence"])


def test_handoff_phrase_is_not_a_funds_transfer():
    assert t("transfer_funds").severity == "irreversible" and t("transfer_to_agent").severity == "state_changing"


# ---- rule table integrity --------------------------------------------------------------------------------------------
def test_every_rule_has_a_rationale_and_valid_severity():
    groups = [RULES["name_rules"], RULES["name_phrase_rules"], RULES["action_rules"], RULES["sql_rules"], RULES["http_rules"], RULES["description_layer"]["rules"],
              RULES["description_layer"]["phrase_rules"]]
    ids = []
    for g in groups:
        for rule in g:
            assert rule["severity"] in SEVERITIES and isinstance(rule["why"], str) and 8 < len(rule["why"]) < 160, rule["id"]
            ids.append(rule["id"])
    assert len(ids) == len(set(ids))
    assert all(i.startswith("D-DESC-") for i in ids if i.startswith("D-"))
    assert all(i.startswith("D-DESC-") for g in (RULES["description_layer"]["rules"], RULES["description_layer"]["phrase_rules"]) for i in [r["id"] for r in g])
    assert len(RULES["shell"]["irreversible_patterns"]) == len(RULES["shell"]["irreversible_pattern_notes"])
    for p in RULES["shell"]["irreversible_patterns"] + RULES["shell"]["editing_patterns"] + RULES["shell"]["read_patterns"]:
        re.compile(p)
    for rule in RULES["description_layer"]["phrase_rules"]:
        re.compile(rule["pattern"])


def test_no_description_or_action_vocabulary_is_hard_coded_in_the_module():
    src = Path(sev_mod.__file__).read_text()
    dl = RULES["description_layer"]
    words = {w.split()[0] for r in dl["rules"] for w in r.get("verbs", []) + r.get("ambiguous", [])} | {w for r in RULES["action_rules"] for w in r["words"]}
    words |= set(dl["verb_cues"]) | set(dl["determiners"]) | set(dl["negators"]) | set(dl["noun_prepositions"])
    words |= set(RULES["shell"]["editing_commands"]) | set(RULES["shell"]["destructive_commands"])
    words -= {"name", "tool", "it", "id", "shell"}
    leaked = sorted(w for w in words if f'"{w}"' in src or f"'{w}'" in src)
    assert leaked == []


# ---- anti-overfitting: no hand-check tool name in rules or code -----------------------------------------------------
HANDCHECK_NAMES = ["plinth_ops", "cobalt", "juniper_batch", "handler_7", "reconcile_ledger", "sync_all", "relay", "backup_service", "wicket", "harbor", "gauge",
                   "flux", "ember", "get_user_choice", "ticket_system", "payment_api", "email_message", "transfer_to_agent", "do_it", "trim_end",
                   "load_web_page", "quick_research", "tinyfish_scrape", "wait_for_crew_completion", "load_memory", "postAsync", "deleteAsync",
                   "apply_patch_tool", "execute_bash", "get_cluster_info"]


def test_no_hand_check_tool_name_appears_in_rules_or_code():
    base = Path(sev_mod.__file__).parent
    texts = {p.name: p.read_text().lower() for p in [base / "severity.py", base / "data" / "severity_rules.json"]}
    for name in HANDCHECK_NAMES:
        forms = {name.lower(), name.lower().replace("_", " ")}
        for fn, text in texts.items():
            for form in forms:
                assert not re.search(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])", text), (name, fn)
