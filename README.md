# Haitem

## Public export-licence decision breakdown

The optional exporter chart reads the Finnish Government's public plenary-session
archive at <https://valtioneuvosto.fi/paatokset/valtioneuvoston-yleisistunto>.
The archive exposes annual pages and pagination as ordinary HTML links. Haitem
follows those links, then reads the linked session pages and selects decision
titles containing “vientiluvan myöntäminen”. Retrieved annual JSON is
stored in `data/export-licences/`.

The current extraction keeps the decision ID, session date, Finnish decision
title, exporter text when present, and source decision/session URLs. Missing
exporter names remain null and are reported in the UI. Exporter grouping only
normalizes case and whitespace.
