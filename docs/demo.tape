# The README's demo GIF. Render with VHS (brew install vhs), from the repo root:
#   vhs docs/demo.tape
# It needs the sandbox image and the eval run folders (runs/ is local, not in git).

Output docs/demo.gif
Set Shell "bash"
Set FontSize 15
Set Width 1200
Set Height 720
Set Theme "Catppuccin Mocha"
Set TypingSpeed 40ms

Hide
Type "source .venv/bin/activate && clear" Enter
Show

Type "# A repair from a recorded model reply: real sandbox, hidden tests, no API key" Enter
Sleep 500ms
Type "make demo" Enter
Sleep 6s

Type "clear" Enter
Type "# A real two-attempt repair from the MutBench test run: the failing test fixes the bug" Enter
Sleep 500ms
Type "patchloop replay runs/eval/mutbench-test/mutbench_131_swap_boolean_0/full/r0" Enter
Sleep 9s
