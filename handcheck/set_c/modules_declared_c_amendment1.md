# Amendment 1 to modules_declared_c.md (2026-10-05)

`modules_declared_c.md` was written first and is unchanged. After running the fixed extraction on the declared modules, the yield was **11 syntax matches, of which 4 are not agent-callable tools, and 22 tool classes skipped** because their `name` / `description` are not string constants in the class body. Only counts and class names were seen at this point, no tool descriptions. Two amendments, both decided from the yield and from tool role, never from severity:

1. **Pattern widened for the already-declared modules**: a class also counts when `name` and `description` are given by a property or method whose body is a single `return` of a string constant (or of a constant name defined in the same module). Same modules, same "whole module, every public tool" rule.
2. **Role exclusions** (not tools an agent calls; they only matched "public function with a docstring"): `get_runner_prompt`, `get_validator_prompt`, `reliable_function_wrapper` (ag2 reliable), `create_output_schema_file` (Codex schema helper). The remaining matches stay.

No module was added. The stop rule in `modules_declared_c.md` applies to what is left: if fewer than 50 distinct external tools remain, the build says so and the composition target of at least 50% external is reported as not met rather than relaxed.
