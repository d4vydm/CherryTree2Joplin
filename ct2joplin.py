import sys
import os
import subprocess
import re
import argparse
from pathlib import Path
import shutil
import sqlite3


##################################################
# Global vars
HTMLIMPORTDIR = "htmlimport"
MDIMPORTDIR = "mdimport"

VERBOSE = False
JOPLIN_IMPORT = False
KEEP_PARENT_NODES = False
KEEP_UNDERSCORES = False

JOPLIN_CONFIG_DIR = ""
JOPLIN_RESOURCE_DIR = ""
JOPLIN_SQLLITE_FILE = ""

HTML_ENTITIES = { 
    "&nbsp;" : " ",
    "&lt;" : "<",
    "&gt;" : ">",
    "&amp;" : "&",
    "&quot;" : "\"",
    "&apos;" : "\'",
    "&euro;" : "€",
}
#Source: https://www.w3schools.com/HTML/html_entities.asp


##################################################
# Functions
def get_note_filenames(ct_html_dir):
    """
    From the given cherrytree html dir parse the files and get the filenames for the html and md files
    """
    exclude = ['index.html']

    files_html = []
    for f in os.listdir(ct_html_dir):
        if f.endswith('.html') & (f not in exclude):
            files_html.append(f)

    files_without_ext = list(map(lambda s: s.rsplit('.html')[0], files_html))

    files_md = list(map(lambda s: s+'.md', files_without_ext))
    if not KEEP_UNDERSCORES:
        # Get rid of the underscores
        files_md = list(map(lambda s: s.replace('_', ' '), files_md))

    return files_html, files_md


def get_joplin_resourceid_filename_mapping(ct_html_dir):
    """
    Function imports HTML files in the given directory into Joplin. Joplin import any referenced files into the Joplin resources directory.
    Files are in the "images" or "EmbeddedFiles" subdirectory.
    Using SQLlite on the Joplin DB to query Joplin resource ID vs Filename mapping
    Return value iis a list of tuples: [(id1, name1), (id2, name2), ...]
    """
    resource_id_name = []

    # Create temporary import dir
    html_base_dir = create_directory(ct_html_dir, HTMLIMPORTDIR)

    # Copy html files to the html_base_dir temporary directory
    copy_files_from_to(ct_html_dir, html_base_dir, ".html", ['index.html'])

    # Copy image files to the html_base_dir directory
    html_images_olddir = os.path.join(ct_html_dir, "images")
    html_images_newdir = create_directory(html_base_dir, "images")
    copy_files_from_to(html_images_olddir,
                       html_images_newdir, ".png", ['home.png'])

    # Copy embedded files dir to the html_base_dir dir
    html_files_olddir = os.path.join(ct_html_dir, "EmbeddedFiles")
    html_files_newdir = create_directory(html_base_dir, "EmbeddedFiles")
    copy_files_from_to(html_files_olddir, html_files_newdir)

    # Import tmp dir into Joplin
    import_in_joplin(html_base_dir, "md")

    # Query the sqlite database for the resource id's and filenames
    con = sqlite3.connect(JOPLIN_SQLLITE_FILE)
    cur = con.cursor()
    cur.execute("select id,title from resources")
    resource_id_name = cur.fetchall()
    con.close()

    # Delete imported tmp dir from Joplin
    # Remark deleting notes from Joplin does not delete the resource form the resources dir!
    delete_notebook_from_joplin(HTMLIMPORTDIR)

    # Delete temporary import dir
    # TODO

    return resource_id_name


def convertHTMLtoMD(file_html, file_md, resource_id_name):
    """
    Convert given html file to md file
    If image or file references are in the file, lookup the ref in the given resource_id_name and replace the name with the Joplin id in the resulting md file
    """

    # Convert using pandoc
    if VERBOSE:
        print("Converting: " + file_html)

    subprocess.call('pandoc -t markdown_strict '
                    + "\"" + file_html + "\""
                    + " -o " + "\"" + file_md + "\"", shell=True)  # Put filename in double quotes as strings are argument to pandoc which is a subprocess call and not python call

    # Cleanup md files
    with open(file_md, 'r') as file:
        data = file.read()

        # Replacements html entities in md files
        for e, v in HTML_ENTITIES.items():
            data = data.replace(e, v)

        # Fix file references in md files
        # Example:
        #   REPLACE: ![](images/file.png)
        #   WITH: ![file.png](:be0a5bce619847c8985cb32028d7af9f)
        # TODO: with regex re.match() or re.sub() this could be more efficient
        for id, name in resource_id_name:
            data = data.replace(
                "![](images/%s)" % name, "![%s](:/%s)" % (name, id))
    
    with open(file_md, 'w') as file:
        if VERBOSE:
            print("Updating image refs in md file " + file_md)
        file.write(data)

    return 1


# def find_resource_id_by_name(resource_id_name, name):
#     """
#     From the resource_id_name list of tupples,
#     returns the resource id (tupple value 0)
#     where name matches the name in the tupple (value 1)
#     """
#     tuplist = [r for r in resource_id_name if r[1] == name]

#     if len(tuplist) == 0:
#         if VERBOSE:
#             print("Warning: resource not found: " + name)
#         return -1
#     if len(tuplist) > 1:
#         if VERBOSE:
#             print("Warning: multiple resource hits during resource name search: " + name)
#         return -1

#     tup = tuplist[0]
#     resource_id = tup[0]

#     return resource_id


def delete_parent_md_file_from_dir(dir):
    """
    Walk through every directory and subdirectory in the given dir and delete corresponding (same name) .md file
    """
    if VERBOSE:
        print("\nWalking: " + dir)

    # Remark: Tried below with os.walk but ran into weird behaviour

    files_and_dirs = os.listdir(dir)  # listdir returns files and directories
    file_map = map(lambda f: f if os.path.isfile(os.path.join(
        dir, f)) else None, files_and_dirs)  # Get the files only
    files = list(filter(None, file_map))
    dir_map = map(lambda d: d if os.path.isdir(os.path.join(dir, d))
                  else None, files_and_dirs)  # Get the dirs only
    dirs = list(filter(None, dir_map))

    # Delete corresponding files
    for d in dirs:
        if d+".md" in files:
            if VERBOSE:
                print("Deleting: " + os.path.join(dir, d + ".md"))
            os.remove(os.path.join(dir, d + ".md"))
    # Run function on dir
    for d in dirs:
        delete_parent_md_file_from_dir(os.path.join(dir, d))

    return 1


def import_in_joplin(d, format='md'):
    """
    Import the given dir into Joplin
    Default format is md (markdown)
    """

    if VERBOSE:
        print("Importing notebook: " + d)
    command = ['joplin', 'import', '--format', format, d]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode == 0:
        if VERBOSE:
            print(result.stdout)
            print("...ok")
    else:
        if VERBOSE:
            print(result.stdout)
            print(result.stderr)
            print(
                "...oops, something went wrong. Check Joplin import output for details.")

    return 1


def delete_notebook_from_joplin(name):
    """
    Delete notebook with name from Joplin
    """

    if VERBOSE:
        print("Deleting notebook: " + name)
    command = ['joplin', 'rmbook', name, "-f"]
    result = subprocess.run(command, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, universal_newlines=True)
    if result.returncode == 0:
        if VERBOSE:
            print(result.stdout)
            print("...ok")
    else:
        if VERBOSE:
            print(result.stdout)
            print(result.stderr)
            print(
                "...oops, something went wrong. Check Joplin import output for details.")

    return 1


def create_directory(basedir, name):
    """
    Create directory under basedir with name
    """
    newdir = re.escape(os.path.join(basedir, name))
    try:
        if VERBOSE:
            print("Creating import dir: " + newdir)
        os.mkdir(newdir)
    except OSError as error:
        print(error)

    return newdir


def copy_files_from_to(from_dir, to_dir, filetype='', exclude=[]):
    """
    Copies all files with given filetype in the from_dir to the to_dir
    Exclude files in the exclude param
    """

    for f in os.listdir(from_dir):
        if ((filetype == '') | f.endswith(filetype)) & (f not in exclude):
            try:
                f_fp = os.path.join(from_dir, f)
                if VERBOSE:
                    print("Coping file " + f_fp + " to " + to_dir, end='')
                shutil.copy2(f_fp, to_dir)

            except OSError as error:
                if error.errno == 17:
                    print(" ...skip, file exists")
                else:
                    print(error)

            print()

    return 1


def create_dir_for_mdfile(md_base_dir, mdfile):
    """
    Create directory (full directory with intermediate dirs if needed) for the given mdfile
    Returns path for the directory
    """
    # Create path from the name of the file based on splitting on "--"
    # mdfile has format: Parent--Child1--Child2--Leaf.md
    # All before last is the name of the Parents/Childs
    parents = mdfile.split("--")[:-1]

    # Build path for this mdfile
    newpath = ""
    for p in parents:
        newpath = os.path.join(newpath, p)

    # Create the directories in newpath recursively if not exist
    try:
        if VERBOSE:
            print("Creating directory: " + os.path.join(md_base_dir, newpath), end='')
        os.makedirs(os.path.join(md_base_dir, newpath))
    except OSError as error:
        if error.errno == 17:
            print(" ...skip, directory exists")
        else:
            print(error)

    if VERBOSE:
        print()

    return newpath


def move_mdfile_to_dir(md_base_dir, mdfilepath, mdfile):
    """
    Move md file from md_base_dir to new mdfilepath
    """
    # Create full pathnames for the files
    mdfile_currentfp = os.path.join(md_base_dir, mdfile)
    # Last item is the name of the Leaf
    mdfilename = mdfile.split("--")[-1]
    mdfile_newfp = os.path.join(md_base_dir, mdfilepath, mdfilename)

    # Move md file
    try:
        if VERBOSE:
            print("Moving file: " + mdfile_currentfp)
        os.rename(mdfile_currentfp, mdfile_newfp)
    except OSError as error:
        print(error)

    if VERBOSE:
        print()


##################################################
# Main
# TODO: Fix bug with dashes or spaces in name of directory
# TODO: Fix bug with escaping special chars in the content
# TODO: Fix bug inserting HTML color tags in content
def main(ct_html_dir):
    if VERBOSE:
        print("Starting conversion...\n")

    # Create import directory
    md_base_dir = create_directory(ct_html_dir, MDIMPORTDIR)

    # Get the note filenames to process
    files_html, files_md = get_note_filenames(ct_html_dir)

    # Get resource ID vs filename mapping via temporary Joplin import of the HTML files
    resource_id_name = get_joplin_resourceid_filename_mapping(ct_html_dir)

    # Convert original html files to md
    for _, (file_html, file_md) in enumerate(zip(files_html, files_md)):
        convertHTMLtoMD(
            os.path.join(ct_html_dir, file_html),
            os.path.join(ct_html_dir, MDIMPORTDIR, file_md),
            resource_id_name
        )

    # Create directory tree structure and move the md files
    for mdfile in files_md:
        # Create directory for mdfile
        mdfilepath = create_dir_for_mdfile(md_base_dir, mdfile)

        # Move md file to new directory
        move_mdfile_to_dir(md_base_dir, mdfilepath, mdfile)

    if VERBOSE:
        print()

    # For each directory, check for complementary named .md file and delete it
    if not KEEP_PARENT_NODES:
        delete_parent_md_file_from_dir(md_base_dir)
        if VERBOSE:
            print()

    # Import all dirs in the importdir into joplin seperatly
    if JOPLIN_IMPORT:
        if VERBOSE:
            print("Importing to Joplin...")
        # listdir returns files and directories
        files_and_dirs = os.listdir(md_base_dir)
        # Get the dirs only
        dir_map = map(lambda d: d if os.path.isdir(os.path.join(md_base_dir, d))
                      else None, files_and_dirs)
        dirs = list(filter(None, dir_map))

        for d in dirs:
            import_in_joplin(re.escape(os.path.join(md_base_dir, d)))

    # Cleanup
    #TODO

    # Ready
    if VERBOSE:
        print("\nDone.\n\n")


if __name__ in ('__main__'):
    epilog = "\
    CherryTree exports parent-child-leaf relationship using double dash (e.g. Parent--Child1--Child2--Leaf.html).\
     Spaces are replaced with underscore (Parent--Child1--Child2--Leaf_with_spaces.html).\
     Special chars are not escaped (Parent--Child1--Child_with_(paranthesis)_and_stuff--Leaf.html).\
     Joplin has the concept of notebooks and notes. A notebook itself has no content, only notes and other notebooks.\
     Cherrytree does allow each node to have content.\
     By default we assume parent nodes do not have content, as Joplin sees these as notebooks.\
     Only leafs have content and are considered notes.\
     If you do wish to keep the content of the parent nodes, use the -kp flag\
    \
    The program converts the flat directory HTML export from CherryTree to a structured MD files tree\
    We use the joplin import function to import from a directory\
    "

    parser = argparse.ArgumentParser(
        description="Import CherryTree notes into Joplin. Dependencies: pandoc, joplin cli. (Author: D4vyDM)")
    parser.epilog = epilog

    parser.add_argument("--version", action="version", version="%(prog)s v1.0")
    parser.add_argument("-v", "--verbose", action="store_true", default=False)
    parser.add_argument("-kp", "--keep_parent_notes", action="store_true", default=False,
                        help="By default the program assumes only leaf nodes have notes. With this flag, also import parent nodes note data.")
    parser.add_argument("-ku", "--keep_underscores", action="store_true", default=False,
                        help="By default underscores in node names are replaced with spaces. With this flag we keep underscores in node names.")
    parser.add_argument("-ji", "--joplin_import", action="store_true", default=False,
                        help="Import converted data directly into Joplin")
    parser.add_argument("-jc", "--joplin_config_dir", action="store", default="",
                        help="Pass the path of the Joplin configuration directory")                        
    parser.add_argument("directory", action="store",
                        help="directory containing the exported CherryTree html files")
    args = parser.parse_args()

    # Parse arguments
    VERBOSE = args.verbose
    JOPLIN_IMPORT = args.joplin_import
    KEEP_PARENT_NODES = args.keep_parent_notes
    KEEP_UNDERSCORES = args.keep_underscores
    JOPLIN_CONFIG_DIR = args.joplin_config_dir

    # Set joplin resource dir
    if JOPLIN_IMPORT:
        platform = sys.platform
        if platform == "linux" or platform == "linux2":
            # linux
            if JOPLIN_CONFIG_DIR != "":
                joplinconf = JOPLIN_CONFIG_DIR
            else: #Default
                joplinconf = os.path.join(str(Path.home()), ".config/joplin-desktop/")
            JOPLIN_RESOURCE_DIR = os.path.join(joplinconf, 'resources')
            JOPLIN_SQLLITE_FILE = os.path.join(joplinconf, 'database.sqlite')
        elif platform == "darwin":
            # OS X
            print(
                "Exiting... MacOSX platform not implemented.")
        elif platform == "win32":
            # Windows...
            print(
                "Exiting... Windows platform not implemented.")

        if VERBOSE:
            print("Joplin sqlite file:" + JOPLIN_SQLLITE_FILE)
            print("Joplin resource dir:" + JOPLIN_RESOURCE_DIR)

        if not os.path.exists(JOPLIN_RESOURCE_DIR):
            print(
                "Exiting... The joplin resources directory does not exist.")
            sys.exit()

        if not os.path.exists(JOPLIN_SQLLITE_FILE):
            print(
                "Exiting... The joplin sqllite file does not exist.")
            sys.exit()


    # Check for Pandoc
    # Returns: (0, 'pandoc ...' )
    pandoc_check = subprocess.getstatusoutput('pandoc -v')[0]
    if pandoc_check != 0:
        print('Pandoc not found, please install.')
        sys.exit()

    # Check for Joplin
    # Returns: (0, Joplin CLI Client ...' )
    joplin_cli_check = subprocess.getstatusoutput('joplin version')[0]
    if joplin_cli_check != 0:
        print('Joplin CLI not found, please install.')
        sys.exit()

    # Check directory with html files
    ct_html_dir = args.directory

    # Strip final char from the path if is "/"
    if ct_html_dir[-1] == "/":
        ct_html_dir = ct_html_dir[:len(ct_html_dir)-1]

    # Check if provided directory exists
    if not os.path.exists(ct_html_dir):
        print(
            "Exiting... The provided directory does not exist.")
        sys.exit()

    # Check if directory contains html files
    if not any(f.endswith('.html') for f in os.listdir(ct_html_dir)):
        print(
            "Exiting... The provided directory does not contain any HTML files.")
        sys.exit()


    main(ct_html_dir)
