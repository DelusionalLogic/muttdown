from __future__ import print_function

import argparse
import sys
import re
import os.path

import email
import email.iterators
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import subprocess
from bs4 import UnicodeDammit

import pypandoc

from . import __version__

__name__ = 'muttdown'


def convert_one(part, css):
    text = part.get_payload(None, False)
    # if not text.startswith('!m'):
    #     return None
    extra_args = ["-s"]
    if css:
        extra_args.extend(["-H", css])
    if '\n-- \n' in text:
        pre_signature, signature = text.split('\n-- \n')
        md = pypandoc.convert_text(pre_signature, format="md", to="html5", extra_args=extra_args)
        md += '\n<div class="signature" style="font-size: small"><p>-- <br />'
        md += '<br />'.join(signature.split('\n'))
        md += '</p></div>'
    else:
        md = pypandoc.convert_text(text, format="md", to="html5", extra_args=extra_args)
    message = MIMEText(md, 'html')
    return message

def convert_tree(message, css):
    """Recursively convert a potentially-multipart tree.

    Returns a tuple of (the converted tree, whether any markdown was found)
    """
    ct = message.get_content_type()
    if message.is_multipart():
        if ct == 'multipart/signed':
            # if this is a multipart/signed message, then let's just
            # recurse into the non-signature part
            for part in message.get_payload():
                if part.get_content_type() != 'application/pgp-signature':
                    return convert_tree(part, css)
        else:
            # it's multipart, but not signed. copy it!
            new_root = MIMEMultipart(message.get_content_subtype(), message.get_charset())
            did_conversion = False
            for part in message.get_payload():
                converted_part, this_did_conversion = convert_tree(part, css)
                did_conversion |= this_did_conversion
                new_root.attach(converted_part)
            return new_root, did_conversion
    else:
        # okay, this isn't a multipart type. If it's inline
        # and it's either text/plain or text/markdown, let's convert it
        converted = None
        disposition = message.get('Content-Disposition', 'inline')
        if disposition == 'inline' and ct in ('text/plain', 'text/markdown'):
            converted = convert_one(message, css)
        if converted is not None:
            return converted, True
        return message, False


def rebuild_multipart(mail, css):
    converted, did_any_markdown = convert_tree(mail, css)
    if did_any_markdown:
        new_top = MIMEMultipart('alternative')
        for k, v in mail.items():
            # the fake Bcc header definitely shouldn't keep existing
            if k.lower() == 'bcc':
                del mail[k]
            elif not (k.startswith('Content-') or k.startswith('MIME')):
                new_top.add_header(k, v)
                del mail[k]
        new_top.attach(mail)
        new_top.attach(converted)
        return new_top
    else:
        return mail



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-a', '--account',
        type=str, required=True,
        help='The msmtp account'
    )
    parser.add_argument(
        '-p', '--print-message', action='store_true',
        help='Print the translated message to stdout instead of sending it'
    )
    parser.add_argument(
        '-c', '--css',
        type=str, required=False,
        help='Css file'
    )
    parser.add_argument('-f', '--envelope-from', required=False)
    parser.add_argument('addresses', nargs='*')
    args = parser.parse_args()

    message = sys.stdin.read()

    mail = email.message_from_string(message)

    rebuilt = rebuild_multipart(mail, args.css)

    if args.print_message:
        print(rebuilt.as_string())
    else:
        cmd = ['msmtp', '-a', args.account]
        if args.envelope_from:
            cmd += ['-f', args.envelope_from] + args.addresses
        else:
            cmd += ['-t']


        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, shell=False)
        proc.communicate(rebuilt.as_string().encode())

if __name__ == '__main__':
    main()
