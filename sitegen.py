import click
import os
import json
import jinja2
import markdown
import pyjade
import config
import datetime
import sys
import time
import shutil
from slugify import slugify
from livereload import Server, shell
from htmlmin.minify import html_minify

jinja_env = jinja2.Environment(extensions=['pyjade.ext.jinja.PyJadeExtension'])

def isMoreRecent(original, target):
    origintime = os.path.getmtime(original)
    try:
        generatedtime = os.path.getmtime(target)
    except OSError:
        return True
    if origintime > generatedtime:
        return True
    else:
        return False

def copydirectory(source, target):
    breakpoint = source.split(os.sep)
    for top, dirs, files in os.walk(source):
        for nm in files:
            newpath = []
            path = top.split(os.sep)
            while path[-1] != breakpoint[-1]:
                newpath.insert(0, path.pop())
            newpath = os.path.join('', *newpath)
            if not os.path.exists(os.path.join(target, newpath)):
                os.makedirs(os.path.join(target, newpath))
            if isMoreRecent(os.path.join(top, nm), os.path.join(target, newpath, nm)):
                shutil.copyfile(os.path.join(top, nm), os.path.join(target, newpath, nm))

def changeFileExt(filename, extension):
    filesplit = filename.rsplit('.', 1)
    return filesplit[0] + '.' + extension

def stringtodatetime(datestring):
    return datetime.datetime.strptime(datestring, "%Y-%m-%d %H:%M:%S")

def dateTimePast(datestring):
    testeddatetime = stringtodatetime(datestring)
    currentdatetime = datetime.datetime.now()
    if currentdatetime > testeddatetime:
        return True
    else:
        return False

class site():
    def __init__(self, sitename, force):
        self.location = os.path.join('sites', sitename)
        self.force = force
        self.sitename = sitename
        with open(os.path.join(self.location, 'settings.json')) as jsondata:
            self.settings = json.load(jsondata)
        if config.local:
            self.settings['url'] = 'localhost:8000'
        self.taxonomies = {}
        self.content = self.getcontent()
        template_loader=jinja2.FileSystemLoader(
            [os.path.join(self.location,"templates"),
            os.path.join(os.path.dirname(__file__),"templates")])
        self.templates = jinja2.Environment(loader=template_loader, extensions=['pyjade.ext.jinja.PyJadeExtension'])

    def generatedLocation(self, contenttype, filename):
        filedirectory = filename.split('_')
        filedirectory[-1] = changeFileExt(filedirectory[-1], 'html')
        if config.local:
            generatedtarget = os.path.join('generated', self.sitename)
        else:
            generatedtarget = self.settings['target']
        return os.path.join(generatedtarget, self.settings['content'][contenttype]['target'], *filedirectory)

    def generateurl(self, contenttype, filename):
        filename = filename.split('+', 1)[-1]
        pathstructure = filename.split('_')
        pathstructure[-1] = pathstructure[-1].rsplit('.',1)[0]
        url = 'http://' + self.settings['url'] + self.settings['content'][contenttype]['target'] + '/' + '/'.join(pathstructure)
        if config.local:
            url = url + '.html'
        return url

    def template(self, templatename):
        try:
            return self.templates.get_template(templatename + '.jade')
        except jinja2.exceptions.TemplateNotFound:
            return self.templates.get_template('default.jade')

    def rendertemplate(self, template, context):
        rendercontext = {
                    'settings': self.settings,
                    'content': context
                }
        if 'include' in context:
            for include in context['include']:
                rendercontext[include['content']] = self.content[include['content']][0:include['count']:include['order']]
        return html_minify(template.render(rendercontext))

    def getcontenttypedata(self, contenttype):
        contentlocation = os.path.join(self.location, 'content', contenttype)
        filelist = []
        for filename in os.listdir(contentlocation):
            filepath = os.path.join(contentlocation, filename)
            if filename.lower().endswith('.md'):
                filedata = self.processmd(filepath)
            if filename.lower().endswith('.json'):
                filedata = self.processjson(filepath)
            filedata['filename'] = filename
            filedata['url'] = self.generateurl(contenttype, filename)
            if 'date' in filedata:
                if dateTimePast(filedata['date']):
                    filelist.append(filedata)
            else:
                filelist.append(filedata)
        filelist.sort(key=lambda x: stringtodatetime(x['date']))
        return filelist

    def getcontent(self):
        content = {}
        for contenttype in self.settings['content']:
            self.taxonomies[contenttype] = {}
            content[contenttype] = self.getcontenttypedata(contenttype)
        return content

    def writefile(self, contenttype, context):
        if 'template' in context:
            template = self.template(context['template'])
        else:
            template = self.template(contenttype)
        os.makedirs(os.path.dirname(self.generatedLocation(contenttype, context['filename'])), exist_ok=True)
        with open(self.generatedLocation(contenttype, context['filename'].split('+', 1)[-1]), "w") as generatefile:
            generatefile.write(self.rendertemplate(template, context))
            generatefile.close()

    def getadjacentcontent(self, content, index, direction):
        if direction == 'next':
            adjacent = content[index+1]
        elif direction == 'prev':
            adjacent = content[index-1]
        elif direction == 'first':
            adjacent = content[0]
        elif direction == 'last':
            adjacent = content[-1]
        return {'title': adjacent['title'], 'url': adjacent['url']}

    def processContentType(self, contenttype, content):
        contentlocation = os.path.join(self.location, 'content', contenttype)
        for index, data in enumerate(content):
            self.processTaxonomy(contenttype, index, data)
            if index > 0:
                data['previous'] = self.getadjacentcontent(content, index, 'prev')
                data['first'] = self.getadjacentcontent(content, index, 'first')
            if index+1 is not len(content):
                data['next'] = self.getadjacentcontent(content, index, 'next')
                data['last'] = self.getadjacentcontent(content, index, 'last')
            if isMoreRecent(os.path.join(contentlocation, data['filename']), self.generatedLocation(contenttype, data['filename'])) or self.force:
                self.writefile(contenttype, data)

    def processTaxonomy(self, contenttype, index, data):
        for taxonomy in self.settings['content'][contenttype]['taxonomies']:
            if taxonomy in data:
                if taxonomy not in self.taxonomies[contenttype]:
                    self.taxonomies[contenttype][taxonomy] = {}
                for taxname in data[taxonomy]:
                    if taxname in self.taxonomies[contenttype][taxonomy]:
                        self.taxonomies[contenttype][taxonomy][taxname].append(index)
                    else:
                        self.taxonomies[contenttype][taxonomy][taxname] = [index]

    def filterTaxonomy(self, contenttype, taxonomy=False, taxname=False):
        if subtax:
            filteredlist = []
            filterlist = self.taxonomies[contenttype][taxonomy][taxname]
            for item in filterlist:
                filteredlist.append(self.content[contenttype][item])
        elif taxonomy:
            filteredlist = {}
            filterlist = self.taxonomies[contenttype][taxonomy]
            for taxname, items in filterlist.items():
                if taxname not in filteredlist:
                    filteredlist[taxname] = []
                for item in items:
                    filteredlist[taxname].append(self.content[contenttype][item])
        else:
            filteredlist = self.content[contenttype]
        return filteredlist

    def getArchiveTemplate(self, taxlist=False):
        templatenotfound = True
        if taxlist:
            while templatenotfound:
                if len(taxlist) > 0:
                    if len(taxlist) > 1:
                        taxonomy = '_'.join(taxlist)
                    else:
                        taxonomy = '_' + taxlist[0]
                    try:
                        template = self.templates.get_template('archive' + taxonomy + '.jade')
                    except jinja2.exceptions.TemplateNotFound:
                        taxlist.pop()
                    else:
                        templatenotfound = False
                        return template
                else:
                    templatenotfound = False
        if not templatenotfound:
            template = self.templates.get_template('archive.jade')
            click.echo(template)
            return template

    def generateArchives(self, contenttype):
        template = self.getArchiveTemplate([contenttype])
        os.makedirs(os.path.dirname(self.generatedLocation(contenttype, 'archive_index.html')), exist_ok=True)
        with open(self.generatedLocation(contenttype, 'archive_index.html'), "w") as generatefile:
            generatefile.write(self.rendertemplate(template, self.content[contenttype]))
            generatefile.close()
        for taxonomy, subtaxes in self.taxonomies[contenttype].items():
            template = self.getArchiveTemplate([contenttype, taxonomy])
            with open(self.generatedLocation(contenttype, 'archive_'+taxonomy+'_index.html'), "w") as generatefile:
                generatefile.write(self.rendertemplate(template, {'content': self.filterTaxonomy(contenttype, taxonomy)}))
                generatefile.close()
            for subtax in subtaxes:
                template = self.getArchiveTemplate([contenttype, taxonomy, slugify(str(subtax))])
                os.makedirs(os.path.dirname(self.generatedLocation(contenttype, 'archive_'+ taxonomy + '_' + slugify(str(subtax) + '.html'))), exist_ok=True)
                with open(self.generatedLocation(contenttype, 'archive_'+ taxonomy + '_' + slugify(str(subtax)) +'.html'), "w") as generatefile:
                    generatefile.write(self.rendertemplate(template, {'content': self.filterTaxonomy(contenttype, taxonomy, subtax)}))
                    generatefile.close()

    def collectmedia(self):
        if config.local:
            target = os.path.join('generated', self.sitename, 'media')
        else:
            target = os.path.join(self.target, 'media')
        copydirectory(os.path.join(self.location, 'media'), target)

    def collectstaticimages(self):
        if config.local:
            target = os.path.join('generated', self.sitename, 'static', 'images')
        else:
            target = os.path.join(self.target, 'static', 'images')
        copydirectory(os.path.join(self.location, 'static', 'images'), target)

    def writecss(self, sheet, targetfile):
        with open(sheet) as infile:
            # @import "variables"
            path, file = os.path.split(sheet)
            path = path.split(os.sep)
            newpath = []
            while path[-1] != 'styles':
                newpath.insert(0, path.pop())
            newpath = os.path.join('', *newpath)
            for line in infile:
                if line.startswith('@import'):
                    importcss = line.split(' ')
                    importcss = importcss[1].rstrip().replace('"','')
                    if os.path.isfile(os.path.join(self.location, 'static', 'styles', newpath, importcss + '.styl')):
                        importcss = os.path.join(self.location, 'static', 'styles', newpath, importcss + '.styl')
                    else:
                        importcss = os.path.join('static', 'styles', newpath, importcss + '.styl')
                    targetfile.write("// @import: " + importcss + "\n")
                    self.writecss(importcss, targetfile)
                elif line.startswith('/*'):
                    pass
                elif line.strip() == '':
                    pass
                elif line in ('\n', '\r\n'):
                    pass
                else:
                    targetfile.write(line)
            infile.close()

    def generatecss(self):
        sheetlist = []
        if len(self.settings['fonts']) > 0:
            for font in self.settings['fonts']:
                sheetlist.append(os.path.join('static', 'styles', font + '.styl'))
                if config.local:
                    target = os.path.join('generated', self.sitename, 'static', font)
                else:
                    target = os.path.join(self.target, 'static', font)
                copydirectory(os.path.join('static', 'fonts', font), target)
        for sheet in self.settings['styles']:
            if os.path.isfile(os.path.join(self.location, 'static', 'styles', sheet)):
                sheetlist.append(os.path.join(self.location, 'static', 'styles', sheet))
            else:
                sheetlist.append(os.path.join('static', 'styles', sheet))
        with open(os.path.join(self.location, 'static', 'compiled.styl'), "w") as generatefile:
            for sheet in sheetlist:
                self.writecss(sheet, generatefile)
            generatefile.close()
        if config.local:
            csstarget = os.path.join('generated', self.sitename, 'static', 'style.css')
        else:
            csstarget = os.path.join(self.settings['target'], 'static', 'style.css')
        cmd = 'stylus --compress < ' + os.path.join(self.location, 'static', 'compiled.styl') + ' > ' + csstarget
        os.system(cmd)

    def generatejs(self):
        scriptlist = []
        for script in self.settings['scripts']:
            if os.path.isfile(os.path.join(self.location, 'static', 'javascript', script)):
                scriptlist.append(os.path.join(self.location, 'static', 'javascript', script))
            else:
                scriptlist.append(os.path.join('static', 'javascript', script))
        with open(os.path.join(self.location, 'static', 'script.js'), "w") as generatefile:
            for script in scriptlist:
                with open(script) as infile:
                    for line in infile:
                        generatefile.write(line)
            infile.close()
        generatefile.close()
        if config.local:
            jstarget = os.path.join('generated', self.sitename, 'static', 'script.js')
        else:
            jstarget = os.path.join(self.settings['target'], 'static', 'script.js')
        cmd = 'coffeebar -mo ' + jstarget +' '+ os.path.join(self.location, 'static', 'script.js')
        os.system(cmd)

    def generatestatic(self):
        if(self.settings['scripts']):
            self.generatejs()
        self.generatecss()
        self.collectstaticimages()

    def lineistaxonomy(self, linetax):
        for contenttype, contentattributes in self.settings['content'].items():
            if linetax in contentattributes['taxonomies']:
                return True
        return False

    def processmd(self, filelocation):
        filename = open(filelocation, 'r')
        filedataraw = filename.read().split('\n\n', 1)
        filedata = {}
        for line in filedataraw[0].split('\n'):
            linesplit = line.split(':', 1)
            if self.lineistaxonomy(linesplit[0]):
                filedata[linesplit[0]] = [x.strip() for x in  linesplit[1].split(',')]
            else:
                filedata[linesplit[0]] = linesplit[1].strip()
        filedata['content'] = markdown.markdown(filedataraw[1])
        return filedata

    def processjson(self, filelocation):
        with open(filelocation) as jsondata:
            filedata = json.load(jsondata)
        return filedata

    def compile(self):
        for contenttype, content in self.content.items():
            self.processContentType(contenttype, content)
        with open(os.path.join(self.location,'content.json'), 'w') as outfile:
            json.dump(self.content, outfile, indent = 4)
        for contenttype in self.content:
            self.generateArchives(contenttype)
        #click.echo(self.taxonomies)

@click.group()
def cli():
    pass

@cli.command()
@click.argument('sitename', default='')
def server(sitename):
    server = Server()
    server.watch(os.path.join('sites', sitename, 'content'), shell('python sitegen.py compile '+sitename))
    server.watch(os.path.join('sites', sitename, 'media'), shell('python sitegen.py collectmedia '+sitename))
    server.watch(os.path.join('sites', sitename, 'static', 'javascript'), shell('python sitegen.py generatestatic '+sitename))
    server.watch(os.path.join('sites', sitename, 'static', 'styles'), shell('python sitegen.py generatestatic '+sitename))
    server.watch(os.path.join('sites', sitename, 'templates'), shell('python sitegen.py compile '+sitename+' --force'))
    server.watch(os.path.join('static'), shell('python sitegen.py generatestatic '+sitename))
    server.watch(os.path.join('templates'), shell('python sitegen.py compile '+sitename+' --force'))
    server.serve(root=os.path.join('generated', sitename),port=8000, host='localhost')

@cli.command()
@click.argument('sitename', default='')
@click.option('--force', is_flag=True)
def compile(sitename, force):
    if sitename:
        if os.path.exists(os.path.join('sites', sitename)):
            compilesite = site(sitename, force)
            compilesite.compile()
        else:
            click.echo("Site does not exist.")
    else:
        for sitename in os.listdir(os.path.join('sites')):
            compilesite = site(sitename, force)
            compilesite.compile()

@cli.command()
@click.argument('sitename', default='')
@click.option('--force', is_flag=True)
def generatestatic(sitename, force):
    if sitename:
        if os.path.exists(os.path.join('sites', sitename)):
            compilesite = site(sitename, force)
            compilesite.generatestatic()
        else:
            click.echo("Site does not exist.")
    else:
        for sitename in os.listdir(os.path.join('sites')):
            compilesite = site(sitename, force)
            compilesite.generatestatic()

@cli.command()
@click.argument('sitename', default='')
@click.option('--force', is_flag=True)
def collectmedia(sitename, force):
    if sitename:
        if os.path.exists(os.path.join('sites', sitename)):
            compilesite = site(sitename, force)
            compilesite.collectmedia()
        else:
            click.echo("Site does not exist.")
    else:
        for sitename in os.listdir(os.path.join('sites')):
            compilesite = site(sitename, force)
            compilesite.collectmedia()

@cli.command()
@click.argument('sitename')
def newsite(sitename):
    if not os.path.exists(os.path.join('sites', sitename)):
        click.echo('starting new site ' + sitename)
        title = click.prompt('Website title')
        url = click.prompt('Website url')
        target = click.prompt('Target Directory', default='')
        comics =  click.confirm('Comic site?', default=False, abort=False, prompt_suffix=': ', show_default=True, err=False)
        os.makedirs(os.path.join('sites', sitename))
        subdirs = ['content', 'templates', 'static', ]
        subdirs = {
                'content': ['posts', 'pages'],
                'static': ['images', 'styles', 'javascript'],
                'media': [],
                'templates': [],
            } # end subdirs
        if comics:
            subdirs['content'].append('comics')
        for key, value in subdirs.items():
            os.makedirs(os.path.join('sites', sitename, key))
            for subdir in value:
                os.makedirs(os.path.join('sites', sitename, key, subdir))
        settings = {
                'title': title,
                'url': url,
                'description': '',
                'comic': comics,
                "content": {
                    "posts": {
                        "target": "",
                        "taxonomies": ['categories']
                    },
                    "pages": {
                        "target": "",
                        "taxonomies": []
                    }
                },
                "scripts": [],
                "styles": [],
                "jquery": true,
            }
        if comics:
            settings['content']['comics'] =  {
                                                "target": "comics",
                                                "taxonomies": ["characters", "locations", "chapter"]
                                            }
        if not target:
            settings['target'] = os.path.join('sites', sitename, 'generated')
        else:
            settings['target'] = target
        with open(os.path.join('sites', sitename, 'settings.json'), 'w') as outfile:
            json.dump(settings, outfile, indent=4)
    else:
        click.echo('Site already exists.')

@cli.command()
def sync():
    click.echo('synching site')

if __name__ == '__main__':
    cli()
