# CherryTree to Joplin

This python script converts CherryTree exported HTML files to Joplin.

The tool uses pandoc to convert the html files to md, analyses tree structure of the notes and imports books and notes into joplin using the joplin cli tool.

## How to use

1. Export a CherryTree node to HTML files
Select the node in CherryTree > right click "Nodes Export" > "Export to HTML".
Select "Node and Subnodes" and leave other defaults.
Save into a folder.

2. Run ct2joplin tool 
Use the CherryTree node HTML export directory as argument.
The tool will convert the HTML files into a new subdir "md_to_import". 
A new folder will exist for the selected CherryTree node.

3. Import the converted node in Joplin.
When ct2joplin is run with -ji option, the converted node will be auto imported into Joplin. 
Importing can be done manually in Joplin via "File" > "Import" > "MD - Mardown (Directory)" and choose the node directory created by ct2joplin.


## Dependencies
* Joplin cli https://joplinapp.org/
* pandoc https://pandoc.org/


## Remarks
Make sure to do a quick check on the exported HTML files. Sometimes the exported files have wrong names due to special characters in the name, long names, etc. 
These look like minor naming issues in the CherryTree HTML export but should be fixed before conversion.

Original HTML files are not changed by the tool. All changes are written in the "md_to_import" directory.
