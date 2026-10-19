from string import Template

from patchloop.eval.publish import MARKER, PENDING, Values


def test_missing_values_render_as_pending():
    text = Template("a=$known b=$unknown").substitute(Values(known="1"))
    assert text == f"a=1 b={PENDING}"


def test_results_block_never_eats_the_rest_of_the_readme():
    block = "<!-- RESULTS -->NEW<!-- /RESULTS -->"
    first = "intro\n<!-- RESULTS -->\n## How it works\nmore\n"
    again = "intro\n<!-- RESULTS -->old\n<!-- /RESULTS -->\n## How it works\nmore\n"
    for readme in (first, again):
        out = MARKER.sub(lambda _: block, readme, count=1)
        assert out.startswith("intro\n" + block) and out.endswith("## How it works\nmore\n")
