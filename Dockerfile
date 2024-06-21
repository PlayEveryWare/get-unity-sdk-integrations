FROM python:3.13-rc-windowsservercore⁠ AS builder
ADD . C:/python
WORKDIR C:/python
RUN pip install --target=C:/python -r ./requirements.txt

#download and copy the files
CMD ["C:/main.py"]
COPY C:/installers F:/unity-build-env 
