"""
Model bases for laser cutting: the ground of a site cut as stacked contour layers, laid out on
sheets of the designer's material so that they fit with as little waste as possible.

Independent of HTTP and of the screen.

- terrain:  the ground as a height grid in metres, and an example ground with a site on it
- pieces:   the ground sliced into layers one material thickness apart, each layer split into
            pieces, labelled so a cut piece can be told apart and put back in its place
- nesting:  the pieces laid out on sheets of a given size
- output:   laser files (SVG and DXF, cut lines and engraved lines by colour), a coloured guide
            of each sheet, an assembly map of the whole model and a piece list
"""
