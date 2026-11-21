"""Run an explicit tonal strength sweep against an installed, running Forge build."""
import argparse
import json
from pathlib import Path
import shutil
from gradio_client import Client
from PIL import Image


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:7860')
    parser.add_argument('--prompt',default='a ceramic teapot on a wooden table, a plain wall behind it, soft studio lighting, still life, detailed illustration')
    parser.add_argument('--negative',default='')
    parser.add_argument('--seed',type=int,default=12345)
    parser.add_argument('--width',type=int,default=512);parser.add_argument('--height',type=int,default=512)
    parser.add_argument('--steps',type=int,default=20);parser.add_argument('--cfg',type=float,default=6)
    parser.add_argument('--range',dest='amount',type=float,default=1)
    parser.add_argument('--grid',type=int,default=4)
    parser.add_argument('--attenuations',default='1,0.85,0.5,0')
    parser.add_argument('--reports',type=Path,default=Path('lumex-live-results'))
    args=parser.parse_args()
    if args.seed<0:parser.error('Use a fixed nonnegative seed for comparisons')
    levels=[float(x) for x in args.attenuations.split(',')]
    if not levels or len(levels)>12 or any(not 0<=x<=1 for x in levels):parser.error('Choose 1–12 attenuation values between 0 and 1')
    client=Client(args.url,verbose=False)
    output_ids={x['id'] for x in client.config['components'] if x['props'].get('label')=='Comparison result'}
    endpoints=[x for x in client.config['dependencies'] if output_ids.intersection(x.get('outputs',[])) and len(x.get('inputs',[]))==17]
    if len(endpoints)!=1:raise RuntimeError('A compatible Lum Experiment comparison endpoint was not found; install and restart Forge')
    endpoint=endpoints[0]['api_name'];args.reports.mkdir(parents=True,exist_ok=True);summary=[]
    for i,attenuation in enumerate(levels):
        print(f'Rendering baseline/effect pair at attenuation {attenuation}',flush=True)
        result=client.predict(args.prompt,args.negative,args.seed,args.width,args.height,args.steps,args.cfg,
            0,True,args.grid,args.amount,2,'bilinear',1,attenuation,'tonal',.05,api_name='/'+endpoint)
        if not result or not result[0]:raise RuntimeError(str(result[1] if result else 'Empty result'))
        folder=args.reports/f'{i:02}-attenuation-{attenuation:g}';folder.mkdir(exist_ok=True)
        report=json.loads(result[1]);(folder/'report.json').write_text(json.dumps(report,indent=2))
        for j,item in enumerate(result[0]):
            path=item.get('image') if isinstance(item,dict) else item[0]
            if isinstance(path,dict):path=path['path']
            shutil.copy2(path,folder/f'{j:02}.png')
        if attenuation==1:
            a=Image.open(folder/'00.png').convert('RGB');b=Image.open(folder/'01.png').convert('RGB')
            if a.size!=b.size or a.tobytes()!=b.tobytes():raise RuntimeError('Zero-effect comparison differs from baseline')
        summary.append(report)
    (args.reports/'summary.json').write_text(json.dumps(summary,indent=2))
    print('Sweep completed. Inspect images as well as metrics; perceptual strength is model-dependent.')

if __name__=='__main__':main()
