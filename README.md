# CoatBench

CoatBench is a local workbench for photographed coated test panels. It retains the original exposures and registers repeat views on the same measured plane. Use it to inspect apparent defects, compare finish color and light-dependent details, and save the evidence used for each reading.

## Start

Run `docker compose up --build --wait` and open `http://127.0.0.1:19986`. Choose another local port with `COATBENCH_PORT`. A named volume stores captures and measurements. With Python 3.11 and the pinned dependencies installed, `./start.sh` starts the same workbench.

## Inspect a panel

1. Load the four synthetic sample panels, or add your own photos in **Captures**. Mark the four survey corners, enter panel width and height in millimeters, and register each alternate exposure against corresponding corners. In **Sampling regions**, distinguish inspected areas, material references and exclusions.
2. In **Measure**, use **Scribe exposure width** and mark the ends of a scribe, then select photographed exposed metal and intact film references. The result shows left and right widths from the marked line and leaves total width blank if either side is unknown. **Film coverage** separates exposed metal, film and ambiguous pixels in a selected region. **Pinhole candidates** reports visible closed footprints separately from truncated candidates. Results include an overlay, support and downloadable readings.
3. Use **Surface observations** to review individual candidates, **Polarized glare** and **Raking light comparison** for photograph pairs, and **Coating texture spacing**, **Fine-line network**, **Line scan** or **Coating margin color** for a closer read. **Geometry** saves physical traces and areas. **Panel comparisons** compares comparable retained measurements. **Evidence** builds a ZIP of selected measurements and optional originals. **Received evidence** verifies declared data in an opened evidence ZIP.

Inputs are single-frame PNG, JPEG, WebP or TIFF up to 24 MiB and 12 megapixels. A specimen holds at most 10 captures and 24 regions. Registration and distances are planar. The longest side of the registered sampling plane is limited to 1,800 pixels. Image evidence can identify supported color, apparent surface structure and visible footprints. It cannot establish film thickness, adhesion strength, depth or a material's chemical composition. The sample panels are synthetic.

CoatBench reuses the local CoreSection capture, registration, analysis and evidence libraries. It adds original coated-panel sample imagery and scribe exposure measurement with distinct left and right support, controls and saved evidence.
