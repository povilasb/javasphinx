# Copyright (c) 2012 Bronto Software Inc.
# Licensed under the MIT License

import cPickle as pickle

import sys
import os
import os.path

from optparse import OptionParser

import javalang

import compiler
import util

def find_source_files(input_path, excludes):
    """ Get a list of filenames for all Java source files within the given
    directory.

    """

    java_files = []

    input_path = os.path.normpath(os.path.abspath(input_path))

    for dirpath, dirnames, filenames in os.walk(input_path):
        if is_excluded(dirpath, excludes):
            del dirnames[:]
            continue

        for filename in filenames:
            if filename.endswith(".java"):
                sep = os.path.sep
                full_filename = os.path.join(dirpath, filename)
                if not is_excluded(full_filename, excludes):
                    java_files.append(full_filename)

    return java_files

def write_toc(packages, opts):
    doc = util.Document()
    doc.add_heading('Javadoc', '=')

    toc = util.Directive('toctree')
    toc.add_option('maxdepth', '2')
    doc.add_object(toc)

    packages = list(packages)
    packages.sort()
    for package in packages:
        toc.add_content(package.replace('.', '/') + '/package-index\n')

    filename = 'packages.' + opts.suffix
    fullpath = os.path.join(opts.destdir, filename)

    if os.path.exists(fullpath) and not (opts.force or opts.update):
        sys.stderr.write(fullpath + ' already exists. Use -f to overwrite.\n')
        sys.exit(1)

    f = open(fullpath, 'w')
    f.write(doc.build().encode('utf8'))
    f.close()

def write_documents(documents, sources, opts):
    package_contents = dict()

    # Write individual documents
    for fullname, (package, name, document) in documents.items():
        package_path = package.replace('.', os.sep)
        filebasename = name.replace('.', '-')
        filename = filebasename + '.' + opts.suffix
        dirpath = os.path.join(opts.destdir, package_path)
        fullpath = os.path.join(dirpath, filename)

        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        elif os.path.exists(fullpath) and not (opts.force or opts.update):
            sys.stderr.write(fullpath + ' already exists. Use -f to overwrite.\n')
            sys.exit(1)

        # Add to package indexes
        package_contents.setdefault(package, list()).append(filebasename)

        if opts.update and os.path.exists(fullpath):
            # If the destination file is newer than the source file than skip
            # writing it out
            source_mod_time = os.stat(sources[fullname]).st_mtime
            dest_mod_time = os.stat(fullpath).st_mtime

            if source_mod_time < dest_mod_time:
                continue

        f = open(fullpath, 'w')
        f.write(document.encode('utf8'))
        f.close()

    # Write package-index for each package
    for package, index in package_contents.items():
        doc = util.Document()
        doc.add_heading(package, '=')

        doc.add_object(util.Directive('java:package', package))

        toc = util.Directive('toctree')
        toc.add_option('maxdepth', '1')
        doc.add_object(toc)

        index.sort()
        for filebasename in index:
            toc.add_content(filebasename + '\n')

        package_path = package.replace('.', os.sep)
        filename = 'package-index.' + opts.suffix
        dirpath = os.path.join(opts.destdir, package_path)
        fullpath = os.path.join(dirpath, filename)

        if not os.path.exists(dirpath):
            os.makedirs(dirpath)
        elif os.path.exists(fullpath) and not (opts.force or opts.update):
            sys.stderr.write(fullpath + ' already exists. Use -f to overwrite.\n')
            sys.exit(1)

        f = open(fullpath, 'w')
        f.write(doc.build().encode('utf8'))
        f.close()

def get_newer(a, b):
    if not os.path.exists(a):
        return b

    if not os.path.exists(b):
        return a

    a_mtime = int(os.stat(a).st_mtime)
    b_mtime = int(os.stat(b).st_mtime)

    if a_mtime < b_mtime:
        return b

    return a

def generate_from_source_file(doc_compiler, source_file, cache_dir):
    if cache_dir:
        cache_file = os.path.join(cache_dir, source_file.replace(os.sep, ':')) + '-CACHE'

        if get_newer(source_file, cache_file) == cache_file:
            return pickle.load(open(cache_file))
    else:
        cache_file = None

    f = open(source_file)
    source = f.read()
    f.close()

    try:
        ast = javalang.parse.parse(source)
    except Exception:
        sys.stderr.write('Exception while parsing ' + source_file + '\n')
        raise

    try:
        documents = doc_compiler.compile(ast)
    except Exception:
        sys.stderr.write('Exception while compiling ' + source_file + '\n')
        raise

    if cache_file:
        dump_file = open(cache_file, 'w')
        pickle.dump(documents, dump_file)
        dump_file.close()

    return documents

def generate_documents(source_files, cache_dir, verbose):
    documents = {}
    sources = {}
    doc_compiler = compiler.JavadocRestCompiler()

    for source_file in source_files:
        if verbose:
            print 'Processing', source_file

        this_file_documents = generate_from_source_file(doc_compiler, source_file, cache_dir)

        for fullname in this_file_documents:
            sources[fullname] = source_file

        documents.update(this_file_documents)

    packages = set()

    for package, _, _ in documents.values():
        packages.add(package)

    return packages, documents, sources

def normalize_excludes(rootpath, excludes):
    f_excludes = []
    for exclude in excludes:
        if not os.path.isabs(exclude) and not exclude.startswith(rootpath):
            exclude = os.path.join(rootpath, exclude)
        f_excludes.append(os.path.normpath(exclude) + os.path.sep)
    return f_excludes

def is_excluded(root, excludes):
    sep = os.path.sep
    if not root.endswith(sep):
        root += sep
    for exclude in excludes:
        if root.endswith(exclude):
            return True
    return False

def main(argv=sys.argv):
    parser = OptionParser(
        usage="""\
usage: %prog [options] -o <output_path> <input_path> [exclude_paths, ...]

Look recursively in <input_path> for Java sources files and create reST files
for all non-private classes, organized by package under <output_path>. A package
index (package-index.<ext>) will be created for each package, and a top level
table of contents will be generated named packages.<ext>.

Paths matching any of the given exclude_paths (interpreted as regular
expressions) will be skipped. Also exclude_paths might be a specific file,
e.g. MySourceFile.java

Note: By default this script will not overwrite already created files.""")

    parser.add_option('-o', '--output-dir', action='store', dest='destdir',
                      help='Directory to place all output', default='')
    parser.add_option('-f', '--force', action='store_true', dest='force',
                      help='Overwrite all files')
    parser.add_option('-c', '--cache-dir', action='store', dest='cache_dir',
                      help='Directory to stored cachable output')
    parser.add_option('-u', '--update', action='store_true', dest='update',
                      help='Overwrite new and changed files', default=False)
    parser.add_option('-T', '--no-toc', action='store_true', dest='notoc',
                      help='Don\'t create a table of contents file')
    parser.add_option('-s', '--suffix', action='store', dest='suffix',
                      help='file suffix (default: rst)', default='rst')
    parser.add_option('-I', '--include', action='append', dest='includes',
                      help='Additional input paths to scan', default=[])
    parser.add_option('-v', '--verbose', action='store_true', dest='verbose',
                      help='verbose output')

    (opts, args) = parser.parse_args(argv[1:])

    if not args:
        parser.error('A source path is required.')

    rootpath, excludes = args[0], args[1:]

    input_paths = opts.includes
    input_paths.append(rootpath)

    if not opts.destdir:
        parser.error('An output directory is required.')

    if opts.suffix.startswith('.'):
        opts.suffix = opts.suffix[1:]

    for input_path in input_paths:
        if not os.path.isdir(input_path):
            sys.stderr.write('%s is not a directory.\n' % (input_path,))
            sys.exit(1)

    if not os.path.isdir(opts.destdir):
        os.makedirs(opts.destdir)

    if opts.cache_dir and not os.path.isdir(opts.cache_dir):
        os.makedirs(opts.cache_dir)

    excludes = normalize_excludes(rootpath, excludes)
    source_files = []

    for input_path in input_paths:
        source_files.extend(find_source_files(input_path, excludes))

    packages, documents, sources = generate_documents(source_files, opts.cache_dir, opts.verbose)

    write_documents(documents, sources, opts)

    if not opts.notoc:
        write_toc(packages, opts)
