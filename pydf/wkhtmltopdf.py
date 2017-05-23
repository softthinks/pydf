import asyncio
import re
import subprocess
import tempfile

from pathlib import Path

from .version import VERSION

__all__ = [
    'AsyncPydf',
    'generate_pdf',
    'get_version',
    'get_help',
    'get_extended_help',
]

THIS_DIR = Path(__file__).parent.resolve()
WK_PATH = str(THIS_DIR / 'bin' / 'wkhtmltopdf')


def _execute_wk(*args, input=None):
    """
    Generate path for the wkhtmltopdf binary and execute command.

    :param args: args to pass straight to subprocess.Popen
    :return: stdout, stderr
    """
    wk_args = (WK_PATH,) + args
    return subprocess.run(wk_args, input=input, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _convert_args(py_args):
    cmd_args = []
    for name, value in py_args.items():
        if value in {None, False}:
            continue
        arg_name = '--' + name.replace('_', '-')
        if value is True:
            cmd_args.append(arg_name)
        else:
            cmd_args.extend([arg_name, str(value)])

    # read from stdin and write to stdout
    cmd_args.extend(['-', '-'])
    return cmd_args


def _set_meta_data(pdf_content, **kwargs):
    fields = [
        ('Title', kwargs.get('title')),
        ('Author', kwargs.get('author')),
        ('Subject', kwargs.get('subject')),
        ('Creator', kwargs.get('creator')),
        ('Producer', kwargs.get('producer')),
    ]
    metadata = '\n'.join(f'/{name} ({value})' for name, value in fields if value)
    if metadata:
        pdf_content = re.sub(b'/Title.*\n.*\n/Producer.*', metadata.encode(), pdf_content, count=1)
    return pdf_content


class AsyncPydf:
    def __init__(self, *, max_processes=20, loop=None):
        self.semaphore = asyncio.Semaphore(value=max_processes, loop=loop)
        self.loop = loop
        cache_dir = Path(tempfile.gettempdir()) / 'pydf_cache'
        if not cache_dir.exists():
            Path.mkdir(cache_dir)
        self.cache_dir = str(cache_dir)

    async def generate_pdf(self,
                           html,
                           title=None,
                           author=None,
                           subject=None,
                           creator=None,
                           producer=None,
                           **cmd_args):
        cmd_args.setdefault('cache_dir', self.cache_dir)
        cmd_args = [WK_PATH] + _convert_args(cmd_args)
        async with self.semaphore:
            p = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                loop=self.loop
            )
            p.stdin.write(html.encode())
            p.stdin.close()
            await p.wait()
            pdf_content = await p.stdout.read()
            if p.returncode != 0 and pdf_content[:4] != b'%PDF':
                stderr = await p.stderr.read()
                raise RuntimeError('error running wkhtmltopdf, command: {!r}\n'
                                   'response: "{}"'.format(cmd_args, stderr.strip()))

            return _set_meta_data(
                pdf_content,
                title=title,
                author=author,
                subject=subject,
                creator=creator,
                producer=producer,
            )


def generate_pdf(html, *,
                 title=None,
                 author=None,
                 subject=None,
                 creator=None,
                 producer=None,
                 # from here on arguments are passed via the commandline to wkhtmltopdf
                 cache_dir=None,
                 grayscale=False,
                 lowquality=False,
                 margin_bottom=None,
                 margin_left=None,
                 margin_right=None,
                 margin_top=None,
                 orientation=None,
                 page_height=None,
                 page_width=None,
                 page_size=None,
                 image_dpi=None,
                 image_quality=None,
                 **extra_kwargs):
    """
    Generate a pdf from either a url or a html string.

    After the html and url arguments all other arguments are
    passed straight to wkhtmltopdf

    For details on extra arguments see the output of get_help()
    and get_extended_help()

    All arguments whether specified or caught with extra_kwargs are converted
    to command line args with "'--' + original_name.replace('_', '-')"

    Arguments which are True are passed with no value eg. just --quiet, False
    and None arguments are missed, everything else is passed with str(value).

    :param html: html string to generate pdf from
    :param grayscale: bool
    :param lowquality: bool
    :param margin_bottom: string eg. 10mm
    :param margin_left: string eg. 10mm
    :param margin_right: string eg. 10mm
    :param margin_top: string eg. 10mm
    :param orientation: Portrait or Landscape
    :param page_height: string eg. 10mm
    :param page_width: string eg. 10mm
    :param page_size: string: A4, Letter, etc.
    :param image_dpi: int default 600
    :param image_quality: int default 94
    :param extra_kwargs: any exotic extra options for wkhtmltopdf
    :return: string representing pdf
    """
    if html.lstrip().startswith(('http', 'www')):
        raise ValueError('pdf generation from urls is not supported')

    py_args = dict(
        cache_dir=cache_dir,
        grayscale=grayscale,
        lowquality=lowquality,
        margin_bottom=margin_bottom,
        margin_left=margin_left,
        margin_right=margin_right,
        margin_top=margin_top,
        orientation=orientation,
        page_height=page_height,
        page_width=page_width,
        page_size=page_size,
        image_dpi=image_dpi,
        image_quality=image_quality,
    )
    py_args.update(extra_kwargs)
    cmd_args = _convert_args(py_args)

    p = _execute_wk(*cmd_args, input=html.encode())
    pdf_content = p.stdout

    # it seems wkhtmltopdf's error codes can be false, we'll ignore them if we
    # seem to have generated a pdf
    if p.returncode != 0 and pdf_content[:4] != b'%PDF':
        raise RuntimeError('error running wkhtmltopdf, command: {!r}\n'
                           'response: "{}"'.format(cmd_args, p.stderr.strip()))

    return _set_meta_data(
        pdf_content,
        title=title,
        author=author,
        subject=subject,
        creator=creator,
        producer=producer,
    )


def _string_execute(*args):
    return _execute_wk(*args).stdout.decode().strip(' \n')


def get_version():
    """
    Get version of pydf and wkhtmltopdf binary

    :return: version string
    """
    try:
        wk_version = _string_execute('-V')
    except Exception as e:
        # we catch all errors here to make sure we get a version no matter what
        wk_version = '%s: %s' % (e.__class__.__name__, e)
    return 'pydf version: %s\nwkhtmltopdf version: %s' % (VERSION, wk_version)


def get_help():
    """
    get help string from wkhtmltopdf binary
    uses -h command line option

    :return: help string
    """
    return _string_execute('-h')


def get_extended_help():
    """
    get extended help string from wkhtmltopdf binary
    uses -H command line option

    :return: extended help string
    """
    return _string_execute('-H')
