from pathlib import Path


def make_root(tmp_path: Path, toml: str, configs: dict[str, dict[str, str]]) -> Path:
    (tmp_path / "pkg.toml").write_text(toml)
    cfgdir = tmp_path / "configs"
    for name, files in configs.items():
        for rel, content in files.items():
            p = cfgdir / name / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
    return tmp_path
