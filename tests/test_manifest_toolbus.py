from coolbox.plugins.manifest import load_manifest_document


def test_manifest_toolbus_section_parsed():
    manifest = {
        "profiles": {
            "default": {
                "orchestrator": {},
                "preload": {},
                "recovery": {},
                "plugins": [
                    {
                        "id": "sample",
                        "runtime": {"kind": "native"},
                        "capabilities": {},
                        "io": {},
                        "resources": {},
                        "hooks": {"before": [], "after": [], "on_failure": []},
                        "toolbus": {
                            "invoke": {"tools.sample": "handle"},
                            "stream": {"tools.stream": "streamer"},
                            "subscribe": {"tools.events": "events"},
                        },
                    }
                ],
            }
        }
    }
    document = load_manifest_document(manifest)
    plugin = document.profiles["default"].plugins[0]
    assert plugin.toolbus is not None
    assert plugin.toolbus.invoke == {"tools.sample": "handle"}
    assert plugin.toolbus.stream == {"tools.stream": "streamer"}
    assert plugin.toolbus.subscribe == {"tools.events": "events"}
