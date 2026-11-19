/* Minimal HTTP server replacing abtproxy's local key endpoint.
 * Serves the cached /init/abtproxy/*.json so nx's card pipeline can fetch keys
 * without reaching Bytemark. Routes by path substring; everything else -> 200 {}.
 * Logs each request to /init/keyserve.log. ARM, glibc-2.4 only. */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <fcntl.h>
#include <signal.h>

static char *slurp(const char *path, long *n){
    FILE *f=fopen(path,"rb"); if(!f){*n=0;return NULL;}
    fseek(f,0,SEEK_END); *n=ftell(f); fseek(f,0,SEEK_SET);
    char *b=malloc(*n+1); if(fread(b,1,*n,f)!=(size_t)*n){} b[*n]=0; fclose(f); return b;
}
static void logreq(const char *line){
    int fd=open("/init/keyserve.log",O_WRONLY|O_CREAT|O_APPEND,0644);
    if(fd>=0){ write(fd,line,strlen(line)); write(fd,"\n",1); close(fd); }
}
int main(void){
    signal(SIGPIPE, SIG_IGN);
    int sfd=socket(AF_INET,SOCK_STREAM,0);
    int one=1; setsockopt(sfd,SOL_SOCKET,SO_REUSEADDR,&one,sizeof one);
    struct sockaddr_in a; memset(&a,0,sizeof a);
    a.sin_family=AF_INET; a.sin_addr.s_addr=INADDR_ANY; a.sin_port=htons(80);
    if(bind(sfd,(struct sockaddr*)&a,sizeof a)<0){ logreq("bind failed"); return 1; }
    listen(sfd,16); logreq("keyserve listening on :80");
    for(;;){
        int c=accept(sfd,NULL,NULL); if(c<0) continue;
        char req[4096]; int r=read(c,req,sizeof req-1); if(r<=0){ close(c); continue; }
        req[r]=0;
        char line[256]; int i=0; while(req[i] && req[i]!='\r' && req[i]!='\n' && i<255){ line[i]=req[i]; i++; } line[i]=0;
        logreq(line);
        const char *path=NULL;
        if(strstr(line,"/v1/device/keys")) path="/init/abtproxy/keys.json";
        else if(strstr(line,"/v1/device/labels")) path="/init/abtproxy/labels.json";
        long n=0; char *body=NULL;
        if(path) body=slurp(path,&n);
        if(!body){ body=strdup("{}"); n=2; }
        char hdr[256];
        int hl=snprintf(hdr,sizeof hdr,
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %ld\r\nConnection: close\r\n\r\n",n);
        write(c,hdr,hl); write(c,body,n); free(body); close(c);
    }
}
