# Generated reports

Review pages and decline audit outputs are tracked in Git; large intermediate graph outputs are ignored. Edit source files in ../kg_rootcause, then regenerate the pages.

From Knowledge_graph, regenerate everything with:

```sh
.venv/bin/python -m kg_rootcause.reports --rebuild
```

## Where the graph page logic lives

- Data preparation: `../kg_rootcause/frontend_contract/explorer.py`
- Graph drawing, selection, branching, reason display: `../kg_rootcause/frontend_contract/assets/explorer.js`
- Page markup: `../kg_rootcause/frontend_contract/templates/knowledge_explorer.html`
- Page styles: `../kg_rootcause/frontend_contract/assets/explorer.css` and `standalone.css`
- Offline document wrapper: `../kg_rootcause/reporting/html.py`

The generated HTML embeds its data, CSS, and JavaScript. It has no external script dependency.

Open index.html for the report links. report_manifest.json maps each report to its sources.
