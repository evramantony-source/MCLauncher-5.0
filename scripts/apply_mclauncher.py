#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID = f"{{{ANDROID_NS}}}"
ET.register_namespace("android", ANDROID_NS)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def find_manifest(root: Path) -> Path:
    expected = root / "ZalithLauncher/src/main/AndroidManifest.xml"
    if expected.exists():
        return expected
    fail(f"Expected manifest was not found: {expected}")


def resolve_namespace(module: Path, manifest: Path) -> str:
    for gradle in (module / "build.gradle.kts", module / "build.gradle"):
        if not gradle.exists():
            continue

        text = gradle.read_text(encoding="utf-8", errors="ignore")

        # Direct Gradle declarations.
        for pattern in (
            r'namespace\s*=\s*"([^"]+)"',
            r"namespace\s+'([^']+)'",
            r'applicationId\s*=\s*"([^"]+)"',
            r"applicationId\s+'([^']+)'",
        ):
            match = re.search(pattern, text)
            if match:
                return match.group(1)

        # Kotlin DSL variable declarations, including Zalith's:
        # val zalithPackageName = "com.movtery.zalithlauncher"
        # namespace = zalithPackageName
        variables = dict(
            re.findall(
                r'(?:val|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"([^"]+)"',
                text,
            )
        )

        for assignment in ("namespace", "applicationId"):
            match = re.search(
                rf'{assignment}\s*=\s*([A-Za-z_][A-Za-z0-9_]*)',
                text,
            )
            if match and match.group(1) in variables:
                return variables[match.group(1)]

        if "zalithPackageName" in variables:
            return variables["zalithPackageName"]

    package = ET.parse(manifest).getroot().get("package")
    if package:
        return package

    for source_root in (module / "src/main/java", module / "src/main/kotlin"):
        if not source_root.exists():
            continue
        for source in source_root.rglob("*"):
            if source.suffix not in {".kt", ".java"}:
                continue
            source_text = source.read_text(encoding="utf-8", errors="ignore")
            match = re.search(
                r'^package\s+([A-Za-z_][A-Za-z0-9_.]*)',
                source_text,
                flags=re.MULTILINE,
            )
            if match:
                return match.group(1)

    fail("Could not resolve Android namespace.")


def qualify(name: str, namespace: str) -> str:
    if name.startswith("."):
        return namespace + name
    if "." not in name:
        return namespace + "." + name
    return name


def is_launcher_filter(intent: ET.Element) -> bool:
    actions = {n.get(ANDROID + "name") for n in intent.findall("action")}
    categories = {n.get(ANDROID + "name") for n in intent.findall("category")}
    return (
        "android.intent.action.MAIN" in actions
        and "android.intent.category.LAUNCHER" in categories
    )


def find_original_launcher(manifest: Path, namespace: str) -> str:
    tree = ET.parse(manifest)
    app = tree.getroot().find("application")
    if app is None:
        fail("Manifest has no application element.")

    for tag in ("activity", "activity-alias"):
        for component in app.findall(tag):
            if any(is_launcher_filter(intent) for intent in component.findall("intent-filter")):
                raw = component.get(ANDROID + "name")
                if not raw:
                    fail("Original launcher component has no android:name.")
                return qualify(raw, namespace)

    fail("Could not locate original launcher activity or alias.")


def patch_manifest(manifest: Path, namespace: str, custom_class: str) -> None:
    tree = ET.parse(manifest)
    app = tree.getroot().find("application")
    if app is None:
        fail("Manifest has no application element.")

    for tag in ("activity", "activity-alias"):
        for component in app.findall(tag):
            for intent in list(component.findall("intent-filter")):
                if is_launcher_filter(intent):
                    component.remove(intent)

    fqcn = f"{namespace}.{custom_class}"
    custom = ET.Element("activity")
    custom.set(ANDROID + "name", fqcn)
    custom.set(ANDROID + "exported", "true")

    intent = ET.SubElement(custom, "intent-filter")
    action = ET.SubElement(intent, "action")
    action.set(ANDROID + "name", "android.intent.action.MAIN")
    category = ET.SubElement(intent, "category")
    category.set(ANDROID + "name", "android.intent.category.LAUNCHER")

    app.insert(0, custom)
    tree.write(manifest, encoding="utf-8", xml_declaration=True)


def patch_gradle_properties(root: Path) -> int:
    properties = root / "gradle.properties"
    if not properties.exists():
        return 0

    text = properties.read_text(encoding="utf-8", errors="ignore")
    replacements = {
        "launcher_app_name": "MCLauncher",
        "launcher_name": "MCLauncher",
        "launcher_short_name": "MCL",
    }
    changed = 0

    for key, value in replacements.items():
        pattern = rf'(?m)^{re.escape(key)}=.*$'
        if re.search(pattern, text):
            updated = re.sub(pattern, f"{key}={value}", text)
            if updated != text:
                text = updated
                changed += 1
        else:
            text += f"\n{key}={value}"
            changed += 1

    properties.write_text(text.rstrip() + "\n", encoding="utf-8")
    return changed


def patch_app_name(module: Path) -> int:
    patched = 0
    for strings in module.glob("src/main/res/values*/strings.xml"):
        text = strings.read_text(encoding="utf-8", errors="ignore")
        new = re.sub(
            r'(<string\s+name="app_name"[^>]*>).*?(</string>)',
            r'\1MCLauncher\2',
            text,
            flags=re.DOTALL,
        )
        if new != text:
            strings.write_text(new, encoding="utf-8")
            patched += 1
    return patched


def patch_problematic_string_formats(module: Path) -> int:
    """
    Fix upstream translated strings that contain multiple non-positional Java
    format placeholders. Android expects numbered placeholders such as %1$s and
    %2$d when a string has more than one substitution.
    """
    target_names = (
        "file_invalid_length",
        "terracotta_notification_desc",
    )
    name_group = "|".join(re.escape(name) for name in target_names)

    string_pattern = re.compile(
        rf'(<string\b[^>]*\bname="(?:{name_group})"[^>]*>)'
        rf'(.*?)'
        rf'(</string>)',
        flags=re.DOTALL,
    )
    unnumbered_placeholder = re.compile(
        r'(?<!%)%(?!%|\d+\$)([-#+ 0,(]*\d*(?:\.\d+)?[sSdDfF])'
    )
    numbered_placeholder = re.compile(r'%(?P<position>\d+)\$')

    patched = 0
    values_root = module / "src/main/res"

    for xml_file in values_root.glob("values*/*.xml"):
        original = xml_file.read_text(encoding="utf-8", errors="ignore")

        def patch_string(match: re.Match[str]) -> str:
            nonlocal patched
            opening, body, closing = match.groups()

            existing_positions = [
                int(item.group("position"))
                for item in numbered_placeholder.finditer(body)
            ]
            next_position = max(existing_positions, default=0) + 1

            def number_placeholder(item: re.Match[str]) -> str:
                nonlocal next_position
                replacement = f"%{next_position}${item.group(1)}"
                next_position += 1
                return replacement

            updated_body, count = unnumbered_placeholder.subn(
                number_placeholder,
                body,
            )
            if count:
                patched += count
                return opening + updated_body + closing
            return match.group(0)

        updated = string_pattern.sub(patch_string, original)
        if updated != original:
            xml_file.write_text(updated, encoding="utf-8")

    return patched


def add_notice_asset(module: Path) -> Path:
    target = module / "src/main/assets/mclauncher/UNOFFICIAL_MODIFIED_VERSION.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        """MCLauncher

Unofficial Modified Version

This private build is based on Zalith Launcher 2 and preserves its original
licence and copyright notices. The Android Minecraft runtime remains derived
from the open-source PojavLauncher ecosystem.
""",
        encoding="utf-8",
    )
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--template", required=True)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    template = Path(args.template).resolve()
    if not root.is_dir():
        fail(f"Upstream root not found: {root}")
    if not template.is_file():
        fail(f"UI template not found: {template}")

    module = root / "ZalithLauncher"
    manifest = find_manifest(root)
    namespace = resolve_namespace(module, manifest)
    original = find_original_launcher(manifest, namespace)

    custom_class = "MCLauncherHomeActivity"
    source_dir = module / "src/main/java" / Path(*namespace.split("."))
    source_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / f"{custom_class}.kt"

    code = template.read_text(encoding="utf-8")
    code = code.replace("__PACKAGE__", namespace)
    code = code.replace("__ORIGINAL_ACTIVITY__", original)
    source.write_text(code, encoding="utf-8")

    patch_manifest(manifest, namespace, custom_class)
    property_count = patch_gradle_properties(root)
    label_count = patch_app_name(module)
    format_count = patch_problematic_string_formats(module)
    notice = add_notice_asset(module)

    report = root / "MCLAUNCHER_PATCH_REPORT.txt"
    report.write_text(
        "\n".join(
            [
                "MCLauncher v0.1 patch applied successfully.",
                f"Namespace: {namespace}",
                f"Original launcher activity: {original}",
                f"New launcher activity: {namespace}.{custom_class}",
                f"Custom source: {source.relative_to(root)}",
                f"Manifest: {manifest.relative_to(root)}",
                f"Gradle properties patched: {property_count}",
                f"App-name resource files patched: {label_count}",
                f"String format resources patched: {format_count}",
                f"Notice asset: {notice.relative_to(root)}",
                "Runtime modules modified: no",
                "Original launcher activity preserved: yes",
            ]
        ) + "\n",
        encoding="utf-8",
    )
    print(report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
    
