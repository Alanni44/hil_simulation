"""Fixed, deployment-owned template for the minimal simulator Run service.

The management request names a configuration, but it never grants the caller
access to arbitrary local files or the ability to change the prepared HIL
configuration.  A deployment loads one complete template and CREATE accepts
only that exact snapshot.  The resource bytes are then re-read below the
configured resource root and audited against the frozen formal contract.
"""

import copy
from pathlib import Path

from icd_runtime.errors import ICDError
from icd_runtime.json_codec import canonicalize, loads
from input_simulator.source_inputs import (
    MAX_RESOURCE_BYTES,
    MAX_TOTAL_BYTES,
    SourceInputAuditor,
)


REQUIRED_FIELDS = frozenset({
    "model_id", "profile_ref", "package_ref", "scenario_ref", "mode",
    "source_binding_ref", "link_ids", "run_configuration", "source_inputs",
    "resource_root", "clock_domain_id",
})

FIXTURE_TEMPLATE_FIELDS = frozenset({
    "template_version", "fixture_file", "fixture_key", "profile_ref",
    "resource_root", "clock_domain_id",
})

FIXTURE_TEMPLATE_WITHOUT_RESOURCES_FIELDS = FIXTURE_TEMPLATE_FIELDS | frozenset({
    "run_configuration_resource_overrides",
})

EXTERNAL_TEMPLATE_FIELDS = frozenset({"template_version", "external_file", "profile_ref",
                                      "resource_root", "clock_domain_id"})


def _snapshot(value):
    """Return an independent canonical JSON-domain copy."""
    return loads(canonicalize(value))


class FixedRunTemplate:
    """One immutable, safe-to-use minimal-integration Run template."""

    @classmethod
    def from_document(cls, value, *, base_directory):
        """Load either a full deployment snapshot or its frozen-fixture form.

        The fixture form is intentionally narrow: it extracts the single
        CREATE fixture's ``params`` object from a configuration-owned JSON
        file.  It is useful for the repository's minimal integration template
        without copying a large formal snapshot into a mutable config file.
        """
        if type(base_directory) is not Path:
            base_directory = Path(base_directory)
        if type(value) is dict and set(value) == EXTERNAL_TEMPLATE_FIELDS:
            if value["template_version"] != "1" or type(value["external_file"]) is not str:
                raise ICDError("SCHEMA", "unsupported external fixed template")
            path = (base_directory / value["external_file"]).resolve(strict=False)
            try:
                path.relative_to(base_directory.resolve(strict=True))
                params = loads(path.read_bytes())
            except (OSError, ValueError, ICDError) as error:
                raise ICDError("RESOURCE", "external fixed template is unavailable") from error
            if type(params) is not dict:
                raise ICDError("RESOURCE", "external fixed template is invalid")
            value = {"model_id": params.get("run_configuration", {}).get("model_id"),
                     "profile_ref": value["profile_ref"], "package_ref": params.get("package_ref"),
                     "scenario_ref": params.get("scenario_ref"), "mode": params.get("mode"),
                     "source_binding_ref": params.get("source_binding_ref"), "link_ids": params.get("link_ids"),
                     "run_configuration": params.get("run_configuration"), "source_inputs": params.get("source_inputs"),
                     "resource_root": value["resource_root"], "clock_domain_id": value["clock_domain_id"]}
        if type(value) is dict and set(value) in (FIXTURE_TEMPLATE_FIELDS,
                                                  FIXTURE_TEMPLATE_WITHOUT_RESOURCES_FIELDS):
            if value["template_version"] != "1" or type(value["fixture_file"]) is not str:
                raise ICDError("SCHEMA", "unsupported fixed fixture template")
            fixture_path = (base_directory / value["fixture_file"]).resolve(strict=False)
            try:
                fixture_path.relative_to(base_directory.resolve(strict=True))
                raw = fixture_path.read_bytes()
                fixture = loads(raw)
            except (OSError, ValueError, ICDError) as error:
                raise ICDError("RESOURCE", "fixed template fixture is unavailable") from error
            if (len(raw) > 16 * 1024 * 1024 or type(fixture) is not dict
                    or type(fixture.get(value["fixture_key"])) is not dict):
                raise ICDError("RESOURCE", "fixed template fixture is invalid or too large")
            request = fixture[value["fixture_key"]]
            if (type(request.get("params")) is not dict or request.get("cmd") != "simulator_run_create"):
                raise ICDError("RESOURCE", "fixed template fixture is not a CREATE request")
            params = request["params"]
            run_configuration = _snapshot(params["run_configuration"])
            if "run_configuration_resource_overrides" in value:
                overrides = value["run_configuration_resource_overrides"]
                if (type(overrides) is not dict
                        or set(overrides) != {"terrain_resource_sha256", "obstacle_resource_sha256"}
                        or any(item is not None for item in overrides.values())):
                    raise ICDError("SCHEMA", "fixed template only permits explicit no-resource configuration")
                run_configuration.update(overrides)
            value = {
                "model_id": params["run_configuration"]["model_id"],
                "profile_ref": value["profile_ref"], "package_ref": params["package_ref"],
                "scenario_ref": params["scenario_ref"], "mode": params["mode"],
                "source_binding_ref": params["source_binding_ref"], "link_ids": params["link_ids"],
                "run_configuration": run_configuration, "source_inputs": params["source_inputs"],
                "resource_root": value["resource_root"], "clock_domain_id": value["clock_domain_id"],
            }
        if type(value) is not dict or set(value) != REQUIRED_FIELDS:
            raise ICDError("SCHEMA", "fixed Run template fields differ from the deployment contract")
        root = Path(value["resource_root"])
        if not root.is_absolute():
            root = base_directory / root
        try:
            root = root.resolve(strict=True)
        except OSError as error:
            raise ICDError("RESOURCE", "fixed resource root is unavailable") from error
        if not root.is_dir():
            raise ICDError("RESOURCE", "fixed resource root is not a directory")
        return cls(
            model_id=value["model_id"], profile_ref=value["profile_ref"],
            package_ref=value["package_ref"], scenario_ref=value["scenario_ref"],
            mode=value["mode"], source_binding_ref=value["source_binding_ref"],
            link_ids=value["link_ids"], run_configuration=value["run_configuration"],
            source_inputs=value["source_inputs"], resource_root=root,
            clock_domain_id=value["clock_domain_id"],
        )

    @classmethod
    def load(cls, path):
        """Read a repository deployment template from its explicit config path.

        Repository templates resolve their immutable fixture/resource paths
        below the repository root (the parent of ``config``), never relative
        to the process current directory.
        """
        path = Path(path)
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise ICDError("RESOURCE", "fixed Run template is unavailable") from error
        if len(raw) > 256 * 1024:
            raise ICDError("CAPACITY", "fixed Run template exceeds deployment capacity")
        return cls.from_document(loads(raw), base_directory=path.parent.parent.resolve())

    def __init__(self, *, model_id, profile_ref, package_ref, scenario_ref, mode,
                 source_binding_ref, link_ids, run_configuration, source_inputs,
                 resource_root, clock_domain_id):
        if (type(model_id) is not str or not model_id or type(mode) is not str
                or type(source_binding_ref) is not str or not source_binding_ref
                or type(clock_domain_id) is not str or not clock_domain_id
                or type(link_ids) is not list or not link_ids
                or not isinstance(resource_root, Path) or not resource_root.is_absolute()):
            raise ICDError("SCHEMA", "invalid fixed Run template primitive")
        self.model_id = model_id
        self.profile_ref = _snapshot(profile_ref)
        self.package_ref = _snapshot(package_ref)
        self.scenario_ref = _snapshot(scenario_ref)
        self.mode = mode
        self.source_binding_ref = source_binding_ref
        self.link_ids = _snapshot(link_ids)
        self.run_configuration = _snapshot(run_configuration)
        self.source_inputs = _snapshot(source_inputs)
        self.resource_root = resource_root
        self.clock_domain_id = clock_domain_id

    def _same(self, actual, expected, label):
        if canonicalize(actual) != canonicalize(expected):
            raise ICDError("REFERENCE", "{} differs from the fixed deployment template".format(label))

    def verify_create(self, params, *, baseline_sha256):
        """Reject all configuration drift before touching local resources."""
        if params["baseline_sha256"] != baseline_sha256:
            raise ICDError("BASELINE", "management baseline differs from the frozen contract")
        if params["run_configuration"]["model_id"] != self.model_id:
            raise ICDError("MODEL", "RunConfigure model differs from the fixed deployment template")
        for key, expected in (
                ("package_ref", self.package_ref), ("scenario_ref", self.scenario_ref),
                ("mode", self.mode), ("source_binding_ref", self.source_binding_ref),
                ("link_ids", self.link_ids), ("run_configuration", self.run_configuration),
                ("source_inputs", self.source_inputs)):
            self._same(params[key], expected, key)

    def _resource_refs(self):
        refs = list(self.source_inputs["protocol"]["resources"])
        history = self.source_inputs["history"]
        if history is not None:
            refs.append(history["resource"])
        return refs

    def _read_resource(self, ref):
        name = ref.get("file_name")
        size = ref.get("size_bytes")
        if (type(name) is not str or not name or Path(name).name != name
                or name in (".", "..") or type(size) is not int or not 0 <= size <= MAX_RESOURCE_BYTES):
            raise ICDError("RESOURCE", "fixed resource declaration is unsafe")
        path = (self.resource_root / name).resolve(strict=False)
        try:
            path.relative_to(self.resource_root)
            with path.open("rb") as source:
                raw = source.read(size + 1)
        except (OSError, ValueError) as error:
            raise ICDError("RESOURCE", "fixed source resource is unavailable") from error
        if len(raw) != size:
            raise ICDError("RESOURCE", "fixed source resource size differs")
        return raw

    def audit(self, contract):
        """Read exactly the declared files and prove their source integrity."""
        refs = self._resource_refs()
        if len(refs) > 10000 or len({ref["resource_id"] for ref in refs}) != len(refs):
            raise ICDError("RESOURCE", "fixed source resource IDs are not unique")
        total = sum(ref["size_bytes"] for ref in refs)
        if total > MAX_TOTAL_BYTES:
            raise ICDError("CAPACITY", "fixed source resources exceed deployment capacity")
        resources = {ref["resource_id"]: self._read_resource(ref) for ref in refs}
        return SourceInputAuditor(contract).audit(
            copy.deepcopy(self.source_inputs), resources, model_id=self.model_id)
