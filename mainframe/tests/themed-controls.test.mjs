import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

function rawControls(source) {
  const masked = source.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\/\/[^\n]*|\/\*[\s\S]*?\*\//g,
    match => match.replace(/[^\n]/g, " "));
  return [...masked.matchAll(/\b(?:[A-Za-z_]\w*\s*\.\s*)?(?:Button|TextField|ComboBox|CheckBox)\s*\{/g)]
    .map(match => masked.slice(0, match.index).split("\n").length);
}

test("control lint detects raw and qualified controls but ignores text", () => {
  assert.deepEqual(rawControls('Button {}\nControls.TextField {}\nThemedComboBox {}\n// CheckBox {}'), [1, 2]);
});

test("application QML uses themed controls", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "..");
  const themed = new Set(["ThemedButton.qml", "ThemedTextField.qml", "ThemedComboBox.qml", "ThemedCheckBox.qml"]);
  const problems = readdirSync(root).filter(name => name.endsWith(".qml") && !themed.has(name))
    .flatMap(name => rawControls(readFileSync(join(root, name), "utf8")).map(line => `${name}:${line}`));
  assert.deepEqual(problems, []);
});
